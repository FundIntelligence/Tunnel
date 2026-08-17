"""
Reconciliation engine — fiscal-year-scoped comparison of bank activity vs
audited financials.

Critical design rule:
  Cash position is compared at the FISCAL YEAR-END DATE only, not at the
  bank statement's own ending date.  Statements may spill into the next
  period; pulling the ending-statement balance would create a false variance.

  All other reconciliations (revenue, expenses, loans) are also bounded to
  the fiscal year window so that out-of-period transactions are excluded.

All amounts are integers (cents) internally; KES conversion (/100.0) only at
the result boundary.
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Request-scoped read cache. The five reconciliation sub-calculations each
# independently re-fetch the same audited-financials row and the same
# fiscal-year transaction set (revenue/expenses/loans all pull the identical
# windowed transactions, ~12 paginated round-trips apiece). Within a single
# generate_reconciliation_section() run those reads are deterministic, so we
# memoize them in a ContextVar the orchestrator sets up and tears down. This is
# a pure read cache — it changes no reconciliation math, only how many times the
# same rows are fetched. ContextVar (not a module global) keeps it per-execution
# and avoids cross-request staleness.
_recon_read_cache: contextvars.ContextVar[Optional[Dict[Any, Any]]] = (
    contextvars.ContextVar("_recon_read_cache", default=None)
)


def _cache_get(key: Any) -> Any:
    cache = _recon_read_cache.get()
    if cache is None:
        return None
    return cache.get(key)


def _cache_put(key: Any, value: Any) -> None:
    cache = _recon_read_cache.get()
    if cache is not None:
        cache[key] = value

# Tolerance below which variance is "EXACT_MATCH" (KES 10 = 1000 cents)
_EXACT_MATCH_CENTS = 1_000
# Tolerance below which variance is "ACCEPTABLE_VARIANCE" (5% = 500 basis points)
_ACCEPTABLE_BP = 500

# Roles treated as loan flows
_LOAN_INFLOW_ROLES = {"loan", "loan_inflow", "loan_disbursement"}
_LOAN_OUTFLOW_ROLES = {"loan_repayment"}

# Operational inflow roles (mirrors reconciliation.py allow-list)
_REVENUE_ROLES = {
    "revenue_operational",
    "mpesa_inflow",
    "pesalink_inflow",
    "revenue_pos",
    "revenue_mpesa",
    "customer_payment",
}

# Roles excluded from expense outflows (transfers between own accounts)
_INTERNAL_TRANSFER_ROLES = {"transfer", "internal_transfer"}

# Outflow roles that are NOT operating expenses and must be excluded from the
# expense reconciliation. Without this, the expense calc deny-listed only the
# transfer roles above and summed EVERY other outflow, which:
#   - double-counted loan_repayment (it has its own loan reconciliation below)
#   - counted reversal_debit, whose mirror reversal_credit is NOT counted as
#     revenue, so the pair did not net out
#   - counted needs_review (unclassified) outflows as confirmed expenses
# This asymmetry (revenue allow-listed, expenses deny-listed) inflated
# "Expenses Observed" above "Revenue Observed". — PAR-30
_NON_EXPENSE_OUTFLOW_ROLES = (
    _INTERNAL_TRANSFER_ROLES
    | _LOAN_OUTFLOW_ROLES
    | {"reversal_debit", "needs_review"}
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_supabase():
    from ..db.supabase_client import get_supabase
    return get_supabase()


def _get_audited_financials(deal_id: str) -> Dict[str, Any]:
    """
    Return the most recent audited financials row for this deal.
    Raises ValueError if not found.
    """
    cache_key = ("audited_financials", deal_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    sb = _get_supabase()
    res = (
        sb.table("pds_audited_financials")
        .select("*")
        .eq("deal_id", deal_id)
        .order("financial_year", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise ValueError(
            f"No audited financials found for deal {deal_id}. "
            "Upload audited statements before running reconciliation."
        )
    _cache_put(cache_key, res.data[0])
    return res.data[0]


def _get_fiscal_year_transactions(
    deal_id: str,
    fiscal_start: str,
    fiscal_end: str,
) -> List[Dict[str, Any]]:
    """
    Fetch all raw transactions for the deal within [fiscal_start, fiscal_end]
    joined with their role from pds_txn_entity_map.
    Returns a list of dicts with keys: txn_date, signed_amount_cents, role,
    document_id, account_id, balance_cents (may be None).
    """
    cache_key = ("fiscal_year_txns", deal_id, fiscal_start, fiscal_end)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    sb = _get_supabase()

    # Paginate raw transactions in fiscal window
    txn_rows: List[Dict[str, Any]] = []
    offset = 0
    PAGE = 1000
    while True:
        res = (
            sb.table("pds_raw_transactions")
            .select("id,txn_id,txn_date,signed_amount_cents,balance_cents,document_id,account_id")
            .eq("deal_id", deal_id)
            .gte("txn_date", fiscal_start)
            .lte("txn_date", fiscal_end)
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        chunk = res.data or []
        txn_rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE

    if not txn_rows:
        _cache_put(cache_key, [])
        return []

    # Build txn_id → role map from pds_txn_entity_map.
    # Fetch the whole deal's entity map and filter locally — avoids URL-length
    # overflow when doing a large IN() list over thousands of txn_ids.
    role_map: Dict[str, str] = {}
    em_offset = 0
    while True:
        em_res = (
            sb.table("pds_txn_entity_map")
            .select("txn_id,role")
            .eq("deal_id", deal_id)
            .range(em_offset, em_offset + PAGE - 1)
            .execute()
        )
        for m in (em_res.data or []):
            role_map[m["txn_id"]] = m.get("role") or ""
        if len(em_res.data or []) < PAGE:
            break
        em_offset += PAGE

    # pds_txn_entity_map.txn_id is the raw-transaction PRIMARY KEY (pds_raw_transactions.id,
    # a uuid), NOT the pds_raw_transactions.txn_id business key (text). Looking up by the
    # business key never matched, so every role resolved to "" — which silently zeroed the
    # role-based reconciliations (Revenue Observed = 0, Loan Observed = 0) and over-counted
    # Expenses (its filter passes empty roles, so internal transfers were summed as outflows).
    for row in txn_rows:
        row["role"] = role_map.get(row.get("id", ""), "")

    _cache_put(cache_key, txn_rows)
    return txn_rows


def _variance_status(variance_cents: int, declared_cents: int) -> str:
    if abs(variance_cents) <= _EXACT_MATCH_CENTS:
        return "EXACT_MATCH"
    if declared_cents > 0:
        variance_bp = abs(variance_cents) * 10000 // declared_cents
        if variance_bp <= _ACCEPTABLE_BP:
            return "ACCEPTABLE_VARIANCE"
    return "SIGNIFICANT_VARIANCE"


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: Cash Position Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_cash_position_reconciliation(deal_id: str) -> Dict[str, Any]:
    """
    Compare bank account balances vs audited financials ON FISCAL YEAR-END DATE.

    Strategy:
      Primary — use balance_cents stored per transaction (populated after migration
      010 and re-ingestion).  The last transaction on or before fiscal_year_end
      for each (document_id, account_id) pair carries the actual statement balance.

      Fallback — when balance_cents is not available for a document (pre-migration
      data), compute the net flow for the fiscal year and note it as FLOW_ONLY so
      callers can distinguish absolute-balance matches from flow-only matches.
    """
    af = _get_audited_financials(deal_id)
    fiscal_end: str = af["financial_year_end"]      # e.g. "2025-12-31"
    fiscal_start: str = af["financial_year_start"]  # e.g. "2025-01-01"
    declared_total_cents: int = af.get("cash_and_equivalents_cents") or 0
    cash_breakdown: Dict[str, int] = af.get("cash_breakdown") or {}

    sb = _get_supabase()

    # Collect the last-known balance per document on or before fiscal_year_end.
    # We query across the full statement range (no fiscal_start lower bound) so
    # that statements starting before the fiscal year are handled correctly.
    doc_res = (
        sb.table("pds_documents")
        .select("id,storage_url,source_files")
        .eq("deal_id", deal_id)
        .execute()
    )
    all_docs = doc_res.data or []

    # Deduplicate: when the same bank statement is stored under multiple document_ids
    # (e.g. re-uploaded), keep only one per unique storage_url.
    # Priority 1: prefer the doc that already has balance_cents populated.
    # Priority 2: keep the first seen (insertion order from Supabase).
    doc_ids = [d["id"] for d in all_docs]
    docs_with_balance: set = set()
    if doc_ids:
        bal_check = (
            sb.table("pds_raw_transactions")
            .select("document_id")
            .eq("deal_id", deal_id)
            .in_("document_id", doc_ids)
            .not_.is_("balance_cents", "null")
            .limit(len(doc_ids) * 2)
            .execute()
        )
        docs_with_balance = {r["document_id"] for r in (bal_check.data or [])}

    seen_urls: Dict[str, str] = {}  # url → doc_id to keep
    for d in all_docs:
        url = d.get("storage_url") or d["id"]
        if url not in seen_urls:
            seen_urls[url] = d["id"]
        elif d["id"] in docs_with_balance and seen_urls[url] not in docs_with_balance:
            # upgrade to the doc that has balance data
            seen_urls[url] = d["id"]

    # Build deduplicated map: doc_id → doc
    documents = {d["id"]: d for d in all_docs if seen_urls.get(d.get("storage_url") or d["id"]) == d["id"]}

    bank_balances: List[Dict[str, Any]] = []
    total_bank_cents = 0
    method = "balance_column"  # will downgrade to "flow_derived" if balance_cents absent

    for doc_id, doc in documents.items():
        # Get the last transaction on or before fiscal_year_end that has a balance
        bal_res = (
            sb.table("pds_raw_transactions")
            .select("txn_date,balance_cents,account_id")
            .eq("deal_id", deal_id)
            .eq("document_id", doc_id)
            .lte("txn_date", fiscal_end)
            .not_.is_("balance_cents", "null")
            .order("txn_date", desc=True)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )

        source_label = (
            doc.get("storage_url") or doc_id
        ).replace("inline://", "")

        if bal_res.data:
            row = bal_res.data[0]
            bal_cents = row["balance_cents"]
            bank_balances.append({
                "source": source_label,
                "balance_kes": round(bal_cents / 100, 2),
                "balance_cents": bal_cents,
                "date": row["txn_date"],
                "method": "balance_column",
            })
            total_bank_cents += bal_cents
        else:
            # Fallback: fiscal-year net flow (opening balance unknown)
            flow_res = (
                sb.table("pds_raw_transactions")
                .select("signed_amount_cents")
                .eq("deal_id", deal_id)
                .eq("document_id", doc_id)
                .gte("txn_date", fiscal_start)
                .lte("txn_date", fiscal_end)
                .range(0, 50_000)
                .execute()
            )
            net_flow = sum(r["signed_amount_cents"] for r in (flow_res.data or []))
            if net_flow == 0:
                continue  # document has no transactions in fiscal year
            bank_balances.append({
                "source": source_label,
                "balance_kes": round(net_flow / 100, 2),
                "balance_cents": net_flow,
                "date": fiscal_end,
                "method": "flow_derived",
                "note": "balance_cents not stored; value is net fiscal-year flow only",
            })
            total_bank_cents += net_flow
            method = "flow_derived"

    # Declared balances from cash_breakdown
    declared_balances: List[Dict[str, Any]] = [
        {"account": acct, "balance_kes": round(cents / 100, 2), "balance_cents": cents}
        for acct, cents in cash_breakdown.items()
    ]

    variance_cents = total_bank_cents - declared_total_cents
    variance_kes = round(variance_cents / 100, 2)
    variance_pct = (
        round(variance_cents / declared_total_cents * 100, 2)
        if declared_total_cents > 0
        else None
    )
    status = _variance_status(variance_cents, declared_total_cents)

    return {
        "fiscal_year_end": fiscal_end,
        "method": method,
        "bank_balances": bank_balances,
        "declared_balances": declared_balances,
        "total_bank_kes": round(total_bank_cents / 100, 2),
        "total_declared_kes": round(declared_total_cents / 100, 2),
        "variance_kes": variance_kes,
        "variance_pct": variance_pct,
        "status": status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 2: Revenue Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_revenue_reconciliation(deal_id: str) -> Dict[str, Any]:
    """Compare bank operational inflows vs declared turnover FOR FISCAL YEAR ONLY."""
    af = _get_audited_financials(deal_id)
    fiscal_start: str = af["financial_year_start"]
    fiscal_end: str = af["financial_year_end"]
    declared_revenue_cents: int = af.get("turnover_cents") or 0

    txns = _get_fiscal_year_transactions(deal_id, fiscal_start, fiscal_end)

    bank_inflow_cents = sum(
        r["signed_amount_cents"]
        for r in txns
        if r["signed_amount_cents"] > 0
        and r.get("role") in _REVENUE_ROLES
    )

    gap_cents = declared_revenue_cents - bank_inflow_cents
    gap_pct = (
        round(gap_cents / declared_revenue_cents * 100, 2)
        if declared_revenue_cents > 0
        else None
    )

    if gap_pct is None:
        assessment = "INSUFFICIENT_DATA — no declared revenue"
    elif 0 <= gap_pct <= 15:
        assessment = "HEALTHY — revenue exceeds cash by acceptable accrual margin"
    elif gap_pct < 0:
        assessment = "WARNING — cash exceeds declared revenue (may include financing/loans)"
    else:
        assessment = "RISK — revenue gap too large (>15%)"

    return {
        "fiscal_period": f"{fiscal_start} to {fiscal_end}",
        "bank_inflows_kes": round(bank_inflow_cents / 100, 2),
        "declared_revenue_kes": round(declared_revenue_cents / 100, 2),
        "gap_kes": round(gap_cents / 100, 2),
        "gap_pct": gap_pct,
        "assessment": assessment,
        "transactions_in_period": len(txns),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 3: Expense Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_expense_reconciliation(deal_id: str) -> Dict[str, Any]:
    """Compare bank outflows vs declared expenses FOR FISCAL YEAR ONLY."""
    af = _get_audited_financials(deal_id)
    fiscal_start: str = af["financial_year_start"]
    fiscal_end: str = af["financial_year_end"]

    # Granular cost sub-categories — retained for the gap-explanation narrative
    # only, NOT summed as the reconciliation input. Summing them mis-states the
    # comparison whenever the document's expense breakdown does not partition
    # cleanly into exactly these five fields (an expense line with no matching
    # field is dropped; a line that maps to two is double-counted).
    cost_fields = [
        "cost_of_sales_cents",
        "operating_costs_cents",
        "administrative_costs_cents",
        "staff_costs_cents",
        "finance_costs_cents",
    ]

    # Authoritative reconciliation input: the income statement's OWN stated
    # total-expenses figure, transcribed verbatim by the extractor. Fall back to
    # summing the granular sub-categories only when no stated total is present
    # (legacy pdfplumber extractor, or rows written before migration 018).
    stated_total = af.get("total_expenses_cents")
    if stated_total is not None:
        declared_expenses_cents = int(stated_total)
        declared_expenses_source = "stated_total"
    else:
        declared_expenses_cents = sum(int(af.get(f) or 0) for f in cost_fields)
        declared_expenses_source = "subcategory_sum"

    txns = _get_fiscal_year_transactions(deal_id, fiscal_start, fiscal_end)

    bank_outflow_cents = sum(
        abs(r["signed_amount_cents"])
        for r in txns
        if r["signed_amount_cents"] < 0
        and r.get("role") not in _NON_EXPENSE_OUTFLOW_ROLES
    )

    gap_cents = declared_expenses_cents - bank_outflow_cents
    gap_pct = (
        round(gap_cents / declared_expenses_cents * 100, 2)
        if declared_expenses_cents > 0
        else None
    )

    return {
        "fiscal_period": f"{fiscal_start} to {fiscal_end}",
        "bank_outflows_kes": round(bank_outflow_cents / 100, 2),
        "declared_expenses_kes": round(declared_expenses_cents / 100, 2),
        "declared_expenses_source": declared_expenses_source,
        "gap_kes": round(gap_cents / 100, 2),
        "gap_pct": gap_pct,
        "explanation": (
            "Gap explained by: non-cash expenses (depreciation, amortisation), "
            "accrued payables, inventory build, and opening accruals"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 4: Loan Activity Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_loan_activity_reconciliation(deal_id: str) -> Dict[str, Any]:
    """Compare bank loan flows vs declared net borrowings FOR FISCAL YEAR ONLY."""
    af = _get_audited_financials(deal_id)
    fiscal_start: str = af["financial_year_start"]
    fiscal_end: str = af["financial_year_end"]
    declared_net_borrowing_cents: int = af.get("financing_cashflow_cents") or 0

    txns = _get_fiscal_year_transactions(deal_id, fiscal_start, fiscal_end)

    disbursements_cents = sum(
        r["signed_amount_cents"]
        for r in txns
        if r["signed_amount_cents"] > 0
        and r.get("role") in _LOAN_INFLOW_ROLES
    )
    repayments_cents = sum(
        abs(r["signed_amount_cents"])
        for r in txns
        if r["signed_amount_cents"] < 0
        and r.get("role") in _LOAN_OUTFLOW_ROLES
    )
    bank_net_borrowing_cents = disbursements_cents - repayments_cents

    variance_cents = bank_net_borrowing_cents - declared_net_borrowing_cents
    variance_bp = (
        abs(variance_cents) * 10000 // abs(declared_net_borrowing_cents)
        if declared_net_borrowing_cents != 0
        else None
    )
    variance_pct = (
        round(variance_cents / declared_net_borrowing_cents * 100, 2)
        if declared_net_borrowing_cents != 0
        else None
    )

    if abs(variance_cents) <= _EXACT_MATCH_CENTS:
        status = "EXACT_MATCH"
    elif variance_bp is not None and variance_bp <= _ACCEPTABLE_BP:
        status = "ACCEPTABLE"
    else:
        status = "VARIANCE"

    return {
        "fiscal_period": f"{fiscal_start} to {fiscal_end}",
        "bank_disbursements_kes": round(disbursements_cents / 100, 2),
        "bank_repayments_kes": round(repayments_cents / 100, 2),
        "bank_net_borrowing_kes": round(bank_net_borrowing_cents / 100, 2),
        "declared_net_borrowing_kes": round(declared_net_borrowing_cents / 100, 2),
        "variance_kes": round(variance_cents / 100, 2),
        "variance_pct": variance_pct,
        "status": status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 5: Account Coverage Advisory
# ─────────────────────────────────────────────────────────────────────────────

# Canonical aliases for fuzzy bank name matching.
# Keys are lowercase canonical short-names; values are substrings to search for.
_BANK_ALIASES: Dict[str, List[str]] = {
    "kcb":    ["kcb", "kenya commercial bank"],
    "equity": ["equity"],
    "absa":   ["absa", "barclays"],
    "zemo":   ["zemo"],
    "ncba":   ["ncba", "nic bank", "commercial bank of africa"],
    "coop":   ["co-operative bank", "coop bank", "co-op"],
    "dtb":    ["dtb", "diamond trust"],
    "stanbic":["stanbic"],
    "im bank":["im bank", "imperial bank"],
    "family bank": ["family bank"],
    "prime bank": ["prime bank"],
}


def _advisory_tier(missing_bp: int) -> str:
    """Classify missing-balance severity. Argument is basis points (10000 = 100%)."""
    if missing_bp < 100:    # < 1 %
        return "NEGLIGIBLE"
    if missing_bp < 500:    # < 5 %
        return "MINOR"
    if missing_bp < 1500:   # < 15 %
        return "MATERIAL"
    return "CRITICAL"


def _materiality_of(balance_cents: int, total_cents: int) -> str:
    bp = (balance_cents * 10000 // total_cents) if total_cents else 0
    return _advisory_tier(bp)


def _canonical_key(name: str) -> Optional[str]:
    """Return the canonical alias key for a bank name, or None if unrecognised."""
    n = name.lower()
    for key, aliases in _BANK_ALIASES.items():
        if any(alias in n for alias in aliases):
            return key
    return None


def _source_label(storage_url: str) -> str:
    return storage_url.replace("inline://", "").replace("https://", "")


def calculate_account_coverage(deal_id: str) -> Dict[str, Any]:
    """
    Compare bank accounts declared in audited financials (cash_breakdown)
    against submitted completed documents.

    Returns an advisory dict — NOT a score penalty.
    Advisory tier:
      NEGLIGIBLE  < 1 % of declared cash missing   → proceed, no action needed
      MINOR       1–5 %                             → suggest upload
      MATERIAL    5–15 %                            → strongly recommend upload
      CRITICAL    > 15 %                            → blocks HIGH_CONFIDENCE tier
    """
    af = _get_audited_financials(deal_id)
    cash_breakdown: Dict[str, int] = af.get("cash_breakdown") or {}

    if not cash_breakdown:
        return {
            "status": "SKIPPED",
            "reason": "No cash_breakdown in audited financials",
        }

    sb = _get_supabase()
    doc_res = (
        sb.table("pds_documents")
        .select("id,storage_url,source_files,status")
        .eq("deal_id", deal_id)
        .eq("status", "completed")
        .execute()
    )
    submitted_docs = doc_res.data or []

    # Build set of canonical bank keys present in submitted documents.
    submitted_keys: set = set()
    for doc in submitted_docs:
        url = doc.get("storage_url") or ""
        key = _canonical_key(url)
        if key:
            submitted_keys.add(key)
        # Also scan source_files list if present
        for sf in (doc.get("source_files") or []):
            sf_key = _canonical_key(str(sf))
            if sf_key:
                submitted_keys.add(sf_key)

    total_declared_cents = sum(cash_breakdown.values())
    total_submitted_cents = 0
    account_details: List[Dict[str, Any]] = []

    for bank_name, declared_cents in cash_breakdown.items():
        canonical = _canonical_key(bank_name) or bank_name.lower().strip()
        is_submitted = canonical in submitted_keys
        materiality = _materiality_of(declared_cents, total_declared_cents)

        if is_submitted:
            total_submitted_cents += declared_cents
            account_details.append({
                "bank_name": bank_name,
                "declared_balance_cents": declared_cents,
                "declared_balance_kes": round(declared_cents / 100, 2),
                "status": "SUBMITTED",
                "materiality": materiality,
            })
        else:
            account_details.append({
                "bank_name": bank_name,
                "declared_balance_cents": declared_cents,
                "declared_balance_kes": round(declared_cents / 100, 2),
                "status": "MISSING",
                "materiality": materiality,
            })

    missing_accounts = [a for a in account_details if a["status"] == "MISSING"]
    total_missing_cents = sum(a["declared_balance_cents"] for a in missing_accounts)
    missing_bp = (total_missing_cents * 10000 // total_declared_cents) if total_declared_cents else 0
    coverage_bp = 10000 - missing_bp
    missing_pct = round(missing_bp / 100, 2)
    coverage_pct = round(coverage_bp / 100, 2)
    advisory = _advisory_tier(missing_bp)

    recommendations = {
        "NEGLIGIBLE": "Proceed with analysis. Missing accounts are immaterial.",
        "MINOR":      "Consider uploading missing statements if material activity is suspected.",
        "MATERIAL":   "Strongly recommend uploading missing statements before finalising.",
        "CRITICAL":   "Upload missing statements to unlock HIGH_CONFIDENCE tier.",
    }

    return {
        "coverage_pct": coverage_pct,
        "declared_accounts_count": len(cash_breakdown),
        "submitted_accounts_count": len(cash_breakdown) - len(missing_accounts),
        "missing_accounts_count": len(missing_accounts),
        "missing_balance_cents": total_missing_cents,
        "missing_balance_kes": round(total_missing_cents / 100, 2),
        "missing_pct": missing_pct,
        "advisory_tier": advisory,
        "recommendation": recommendations[advisory],
        "account_details": account_details,
    }
