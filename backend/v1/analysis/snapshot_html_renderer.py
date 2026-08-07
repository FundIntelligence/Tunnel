"""
Snapshot HTML renderer — 3-page Jinja2 HTML snapshot from live deal data.
"""
from __future__ import annotations

import io
import json
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import qrcode
from jinja2 import Environment, FileSystemLoader
from qrcode.image.svg import SvgImage

from ..analytics import CASHFLOW_INFLOW_ROLES, monthly_cashflow as _monthly_cashflow
from ..core.snapshot_engine import decompress_canonical_json_if_needed
from .snapshot_generator import generate_reconciliation_section

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000

MONTH_ABBR = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}

REVENUE_ROLES = {"revenue_operational", "mpesa_inflow", "pesalink_inflow"}

_BANK_ALIASES = [
    ("KCB",         ["kcb", "kenya commercial bank"]),
    ("Equity",      ["equity"]),
    ("Absa",        ["absa", "barclays"]),
    ("Zemo",        ["zemo"]),
    ("NCBA",        ["ncba", "nic bank", "commercial bank of africa"]),
    ("Co-op",       ["co-operative bank", "coop bank", "co-op"]),
    ("DTB",         ["dtb", "diamond trust"]),
    ("Stanbic",     ["stanbic"]),
    ("IM Bank",     ["im bank", "imperial bank"]),
    ("Family Bank", ["family bank"]),
    ("Prime Bank",  ["prime bank"]),
]


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_supabase():
    from ..db.supabase_client import get_supabase
    return get_supabase()


def _paginate(sb, table: str, select_cols: str, deal_id: str) -> List[Dict]:
    rows, offset = [], 0
    while True:
        chunk = (
            sb.table(table)
            .select(select_cols)
            .eq("deal_id", deal_id)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data or []
        )
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def _bank_label(url: str) -> Optional[str]:
    n = (url or "").lower()
    for key, aliases in _BANK_ALIASES:
        if any(a in n for a in aliases):
            return key
    return None


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


def _fmt_kes_compact(cents: int) -> str:
    kes = cents / 100
    if kes >= 1_000_000:
        return f"{kes / 1_000_000:.1f}M"
    if kes >= 1_000:
        return f"{kes / 1_000:.0f}K"
    return f"{kes:,.0f}"


def _fmt_kes_millions(cents: int) -> str:
    return f"KES {cents / 100 / 1_000_000:.1f}M"


_BADGE_VARIANCE_CLASS = {"b-exact": "ok", "b-ok": "ok", "b-warn": "gap", "b-variance": "bad"}


def _status_to_badge(status: str, coverage_incomplete: bool = False):
    """
    Maps a reconciliation status to a (badge_class, badge_label) pair.
    coverage_incomplete distinguishes a gap explainable by missing bank
    statement coverage (amber b-warn) from a gap on otherwise-complete data,
    which is treated as a genuine unexplained variance (red b-variance).
    """
    if status == "EXACT_MATCH":
        return ("b-exact", "Exact match")
    if status in ("ACCEPTABLE", "ACCEPTABLE_VARIANCE", "HEALTHY"):
        return ("b-ok", "Acceptable")
    if coverage_incomplete:
        return ("b-warn", "Gap · coverage incomplete")
    return ("b-variance", "Variance")


def _make_qr_svg(url: str) -> str:
    qr = qrcode.make(url, image_factory=SvgImage)
    buf = io.BytesIO()
    qr.save(buf)
    svg = buf.getvalue().decode("utf-8")
    return svg[svg.find("<svg"):]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def render_snapshot_html(
    deal_id: str,
    view: str = "observed_recon",
    partner_name: Optional[str] = None,
) -> str:
    """
    view: observed_recon (default, existing 3-page flow — branches internally on
          recon_available) | verify (standalone sealed summary page).
    partner_name: when set, the page header shows the partner's name with
          "Intelligence by P/ Parity" credit instead of the plain Parity header.
          Content and figures are identical — only the header branding changes.
    """
    sb = _get_supabase()

    # 1. Deal metadata
    deal = (
        sb.table("pds_deals")
        .select("company_name, currency, analyst_notes")
        .eq("id", deal_id)
        .single()
        .execute()
        .data
    ) or {}
    company_name: str = deal.get("company_name") or "--"
    currency: str     = deal.get("currency") or "KES"
    analyst_notes: str = deal.get("analyst_notes") or ""

    # 2. Snapshot — decode canonical_json
    snap_res = (
        sb.table("pds_snapshots")
        .select("sha256_hash, created_at, canonical_json")
        .eq("deal_id", deal_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    snap: Dict = snap_res.data[0] if snap_res.data else {}
    sha256_hash: str = snap.get("sha256_hash") or ""
    raw_cj = snap.get("canonical_json") or ""
    canonical_str = decompress_canonical_json_if_needed(raw_cj)
    canonical: Dict = json.loads(canonical_str) if canonical_str else {}

    # 3. Documents — credit_scoring_inputs + doc pills (still doc-level ingestion
    # metadata, unrelated to the monthly-cashflow unification below).
    docs = (
        sb.table("pds_documents")
        .select("id, analytics, storage_url, source_files")
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    credit_scoring_inputs_list: List[Dict] = []
    doc_pills: List[Dict] = []
    # PAR-102: document_id -> detected bank label, reused by Inter-Account
    # Transfer Analysis below to name each side of a detected transfer pair.
    doc_bank_by_id: Dict[str, Optional[str]] = {}

    for doc in docs:
        analytics = doc.get("analytics") or {}
        summary   = analytics.get("summary") or {}
        txn_count = summary.get("total_transactions") or 0
        url       = doc.get("storage_url") or ""
        sf_list   = doc.get("source_files") or []

        bank_name = _bank_label(url)
        if not bank_name:
            for sf in sf_list:
                bank_name = _bank_label(str(sf))
                if bank_name:
                    break
        doc_bank_by_id[doc.get("id")] = bank_name
        label = f"{bank_name or 'Bank'} · {txn_count:,} txns"
        doc_pills.append({"label": label, "active": True})

        cs = analytics.get("credit_scoring_inputs") or {}
        if cs:
            credit_scoring_inputs_list.append(cs)

    # 3b. Monthly cashflow + inflow/outflow composition — sourced from the
    # sealed canonical_json (canon_tagged below), via the exact same
    # monthly_cashflow() / CASHFLOW_INFLOW_ROLES that the live
    # /analytics/monthly-cashflow endpoint (backend/v1/analytics.py) uses for
    # the app's Analysis tab. This used to be three independent
    # implementations that could (and did) silently disagree:
    #   1. parity-ingestion/app/analytics.py::monthly_cashflow() — raw
    #      pre-classification credit/debit off the bank statement, cached once
    #      on pds_documents.analytics at ingestion time and never refreshed.
    #   2. backend/v1/analytics.py::monthly_cashflow() — role-classified,
    #      the trusted definition behind the live endpoint / app's Analysis tab.
    #   3. This file's own Composition section — a third, exclude-list based
    #      total that didn't match either of the above.
    # Both the table and the composition section below now derive from #2's
    # exact function and role set, applied to this snapshot's own sealed
    # transactions/txn_entity_map, so there is exactly one definition left.
    canon_role_by_txn: Dict[str, str] = {
        str(m.get("txn_id") or ""): m.get("role", "")
        for m in (canonical.get("txn_entity_map") or [])
    }
    canon_tagged: List[Dict] = []
    for t in canonical.get("transactions") or []:
        txn_date = str(t.get("txn_date") or "")
        if not txn_date:
            continue
        txn_id = str(t.get("id") or t.get("txn_id") or "")
        canon_tagged.append({
            "role": canon_role_by_txn.get(txn_id, ""),
            "amount_cents": int(t.get("signed_amount_cents") or 0),
            "txn_date": txn_date,
            "txn_id": txn_id,
        })

    monthly_merged: Dict[str, Dict[str, int]] = {
        row["month"]: {"inflow_cents": row["inflow_cents"], "outflow_cents": row["outflow_cents"]}
        for row in _monthly_cashflow(canon_tagged)
    }

    # 4. Audited financials (optional — sets recon_available)
    af_result = (
        sb.table("pds_audited_financials")
        .select(
            "loan_breakdown, turnover_cents, profit_before_tax_cents, financial_year, "
            "inventory_cents, cost_of_sales_cents, extraction_confidence"
        )
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    recon_available = len(af_result) > 0
    af: Dict = af_result[0] if recon_available else {}

    # 5. Paginated transactions + roles
    txn_rows = _paginate(
        sb, "pds_raw_transactions",
        "id, txn_date, signed_amount_cents, abs_amount_cents, normalized_descriptor, balance_cents, "
        "account_id, document_id",
        deal_id,
    )
    # PAR-63: entity_id added so Supplier Payment Analysis can attribute spend
    # to a counterparty name (pds_entities), not just a role-level total.
    map_rows   = _paginate(sb, "pds_txn_entity_map", "txn_id, role, entity_id", deal_id)
    role_by_txn = {r["txn_id"]: r["role"] for r in map_rows}
    entity_id_by_txn = {r["txn_id"]: r.get("entity_id") for r in map_rows}

    # PAR-63: entity display names for the Supplier Payment Analysis section.
    # One deal-scoped, paginated fetch (same _paginate helper already used for
    # pds_raw_transactions/pds_txn_entity_map above) — not a per-row lookup.
    entity_rows = _paginate(sb, "pds_entities", "entity_id, display_name", deal_id)
    entity_name_by_id: Dict[str, str] = {
        e["entity_id"]: e.get("display_name") for e in entity_rows
    }

    txns = [{
        "txn_date": t["txn_date"],
        "signed":   t["signed_amount_cents"] or 0,
        # abs_amount_cents was NULL on every row platform-wide until the
        # ingestion fix that stopped stripping it before insert (it was
        # never actually a DB-generated column). Derive it here too, so
        # rows ingested before that fix still render correctly rather than
        # silently zeroing outflow composition and loan activity totals.
        "abs":      t["abs_amount_cents"] if t["abs_amount_cents"] is not None else abs(t["signed_amount_cents"] or 0),
        "desc":     t["normalized_descriptor"] or "",
        "balance":  t["balance_cents"],
        "role":     role_by_txn.get(t["id"], "other"),
        "entity_id": entity_id_by_txn.get(t["id"]),
    } for t in txn_rows]

    # 6. Reconciliation engine (only when audited financials present).
    #    Prefer the reconciliation section SEALED into the snapshot's canonical_json so
    #    the PDF renders the hashed values rather than a live recompute that can drift
    #    from the snapshot. Legacy snapshots written before recon_section was sealed fall
    #    back to a live recompute.
    recon_section: Dict = {}
    if recon_available:
        sealed_recon = canonical.get("recon_section")
        recon_section = sealed_recon if sealed_recon else generate_reconciliation_section(deal_id)

    # 6b. Account coverage advisory — declared accounts (audited Note 11 cash
    #     breakdown) vs submitted statements. Reuse the value already computed
    #     inside the reconciliation section when present. In observed-only state
    #     there are no audited financials to declare accounts against, so the
    #     advisory is unavailable (calculate_account_coverage requires them) —
    #     leave it empty and the template renders an "awaiting" stub.
    if recon_available:
        acct_cov_raw: Dict = recon_section.get("account_coverage") or {}
    else:
        acct_cov_raw = {}

    # ── Active period ──────────────────────────────────────────────────────
    # Drives every "this period" filter below (avg revenue, loan frequency,
    # cashflow rows/notes). When an audited financial year is declared, scope
    # to that calendar year. Otherwise there's no real "year" to scope to —
    # bank-statement-only deals commonly submit a 12-13 month trailing
    # lookback that crosses a calendar year boundary (e.g. Jan 2025-Jan
    # 2026), so filtering by max(txn_years) would keep only the trailing
    # partial year and silently drop every other month. Include every month
    # present instead.
    if recon_available and af.get("financial_year"):
        active_year = str(af["financial_year"])
        _in_active_period = lambda m: m.startswith(f"{active_year}-")
    else:
        active_year = ""
        _in_active_period = lambda m: True

    # ── Computed metrics ──────────────────────────────────────────────────────

    # Avg monthly revenue
    by_month_rev: Dict[str, int] = defaultdict(int)
    for t in txns:
        if t["signed"] > 0 and t["role"] in REVENUE_ROLES:
            m = (t["txn_date"] or "")[:7]
            if _in_active_period(m):
                by_month_rev[m] += t["signed"]
    avg_rev_cents = (
        int(sum(by_month_rev.values()) / len(by_month_rev)) if by_month_rev else 0
    )

    # Inflow composition — CASHFLOW_INFLOW_ROLES include-list, the same
    # definition monthly_merged above and the live endpoint use (see the
    # "Monthly cashflow" comment above for why this used to be a third,
    # independent, exclude-list-based total that didn't match either).
    by_role_in: Dict[str, int] = defaultdict(int)
    total_in = 0
    for t in canon_tagged:
        if t["amount_cents"] > 0 and t["role"] in CASHFLOW_INFLOW_ROLES:
            by_role_in[t["role"]] += t["amount_cents"]
            total_in += t["amount_cents"]

    # Outflow composition — every negative transaction counts, no role
    # exclusions, matching the live endpoint's definition exactly.
    by_role_out: Dict[str, int] = defaultdict(int)
    total_out = 0
    for t in canon_tagged:
        if t["amount_cents"] < 0:
            amt = abs(t["amount_cents"])
            by_role_out[t["role"]] += amt
            total_out += amt

    # Income quality
    op_in = sum(v for k, v in by_role_in.items() if k in REVENUE_ROLES)
    income_quality_pct = (op_in / total_in * 100) if total_in else 0

    # Loan repayment frequency (active year)
    repay_months: Dict[str, int] = defaultdict(int)
    for t in txns:
        if t["role"] == "loan_repayment" and t["signed"] < 0:
            m = (t["txn_date"] or "")[:7]
            if _in_active_period(m):
                repay_months[m] += 1
    loan_freq = (
        sum(repay_months.values()) / len(repay_months) if repay_months else 0
    )
    loan_repayment_txn_count = sum(1 for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0)

    # Aggregate loan cashflows
    loan_disbursed_cents = sum(
        t["signed"] for t in txns if t["role"] == "loan_disbursement" and t["signed"] > 0
    )
    loan_repaid_cents = sum(
        t["abs"] for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0
    )
    loan_net_cents = loan_disbursed_cents - loan_repaid_cents

    # Cash trend (null-safe — balance_cents may be null for pre-migration rows)
    bal_txns = sorted(
        [t for t in txns if t["balance"] is not None],
        key=lambda x: x["txn_date"] or "",
    )
    if bal_txns:
        first_bal = bal_txns[0]["balance"]
        last_bal  = bal_txns[-1]["balance"]
        yoy_pct   = ((last_bal - first_bal) / abs(first_bal) * 100) if first_bal else None
        cash_trend_str = f"{yoy_pct:+.1f}%" if yoy_pct is not None else "--"
        cash_trend_sub = f"{currency} {first_bal/100:,.0f} → {last_bal/100:,.0f} YoY"
    else:
        cash_trend_str = "--"
        cash_trend_sub = "balance data unavailable"

    # Needs-review count
    needs_review_count = sum(1 for t in txns if t["role"] == "needs_review")

    # Tax
    tax_txns = [t for t in txns if t["role"] == "tax_payment" and t["signed"] < 0]
    tax_by_month: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "total": 0})
    for t in tax_txns:
        m = (t["txn_date"] or "")[:7]
        tax_by_month[m]["count"] += 1
        tax_by_month[m]["total"] += t["abs"]
    jan_spike = any(m.endswith("-01") for m in tax_by_month)
    penalty_count = sum(
        1 for t in tax_txns
        if any(k in (t["desc"] or "").upper() for k in ("PENALTY", "PENALT", "SURCHARGE", "FINE"))
    )
    tax_total_cents = sum(t["abs"] for t in tax_txns)
    tax_months_count = len(tax_by_month)
    jan_month = next((m for m in tax_by_month if m.endswith("-01")), None)
    jan_total = tax_by_month[jan_month]["total"] if jan_month else 0

    # Cashflow net-negative months
    period_months = sorted(m for m in monthly_merged if _in_active_period(m))
    neg_months = sorted(
        m for m in period_months
        if (monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"]) < 0
    )
    if neg_months:
        worst = min(
            neg_months,
            key=lambda m: monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"],
        )
        cashflow_note = (
            f"{len(neg_months)} of {len(period_months)} months net-negative. "
            f"Largest deficit in {MONTH_ABBR.get(worst[5:7], worst[5:7])} {worst[:4]}."
        )
    elif period_months:
        cashflow_note = f"All {len(period_months)} months net-positive."
    else:
        cashflow_note = "No cashflow data available."

    # ── Monthly Cashflow Pattern (PAR-63) ─────────────────────────────────────
    # Peak/trough + trend summary over the same monthly_merged/period_months
    # already used above for cashflow_note/neg_months — single source
    # (canonical_json via canon_tagged), confirmed self-consistent (no
    # numerator/denominator split across sources, unlike the bug fixed in
    # Tax Compliance Analysis). No new computation beyond what this file
    # already tracks; this is a one-time summary sentence, not a new series.
    if len(period_months) < 2:
        cashflow_trend_note = "Only one month of data is available — a trend cannot yet be established." if period_months else ""
        cashflow_peak_trough_note = ""
    else:
        nets_by_month = {
            m: monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"]
            for m in period_months
        }
        trough_month = min(nets_by_month, key=lambda m: nets_by_month[m])
        peak_month   = max(nets_by_month, key=lambda m: nets_by_month[m])
        first_net = nets_by_month[period_months[0]]
        last_net  = nets_by_month[period_months[-1]]
        if last_net > first_net:
            trend_clause = "The trend over the observed period is net POSITIVE."
        elif last_net < first_net:
            trend_clause = "The trend over the observed period is net NEGATIVE — recent months show declining net position."
        else:
            trend_clause = "Net position is broadly stable with no clear directional trend."
        cashflow_peak_trough_note = (
            f"Trough of {_fmt_kes(nets_by_month[trough_month])} in "
            f"{MONTH_ABBR.get(trough_month[5:7], trough_month[5:7])} {trough_month[:4]}; "
            f"peak of {_fmt_kes(nets_by_month[peak_month])} in "
            f"{MONTH_ABBR.get(peak_month[5:7], peak_month[5:7])} {peak_month[:4]}."
        )
        cashflow_trend_note = trend_clause

    # ── Period label ────────────────────────────────────────────────────────
    fy = str(af.get("financial_year") or "") if recon_available else ""
    if fy:
        period_label = f"FY{fy} · Jan 1 – Dec 31 {fy}"
    elif txns:
        dates = sorted(t["txn_date"] for t in txns if t["txn_date"])
        period_label = f"FY{dates[-1][:4]} · {dates[0]} – {dates[-1]}"
    else:
        period_label = "--"

    # ── Report ID + QR ──────────────────────────────────────────────────────
    report_id = (
        f"PR-{sha256_hash[:8].upper()}" if sha256_hash
        else f"PR-{uuid.uuid4().hex[:8].upper()}"
    )
    verify_url = f"https://paritytunnel.com/verify/{report_id}"
    qr_svg     = _make_qr_svg(verify_url)
    generated_date = datetime.utcnow().strftime("%B %-d, %Y")

    # ── Tier badge ───────────────────────────────────────────────────────────
    # New design system defines only two tier badge colours: tier-high (green,
    # for MEDIUM/HIGH_CONFIDENCE) and tier-low (amber, for LOW_CONFIDENCE and
    # the no-audited-financials observed state).
    if recon_available:
        recon_tier = recon_section.get("tier") or "LOW_CONFIDENCE"
        tier_badge_class = "tier-high" if recon_tier in ("HIGH_CONFIDENCE", "MEDIUM_CONFIDENCE") else "tier-low"
        tier_badge_text  = f"● {recon_tier} · reconciled"
    else:
        recon_tier       = "OBSERVED"
        tier_badge_class = "tier-low"
        tier_badge_text  = "● Observed · bank data only"

    # ── Data source pills ────────────────────────────────────────────────────
    data_source_pills = list(doc_pills)
    if recon_available:
        fy_label = f"Audited financials · FY{fy}" if fy else "Audited financials"
        data_source_pills.append({"label": fy_label, "active": True})
        data_source_note = (
            "Bank statements + audited financials reconciled · "
            "4-point reconciliation complete"
        )
    else:
        data_source_pills.append({"label": "Audited financials · not submitted", "active": False})
        data_source_note = (
            "Report covers bank-observed data only · "
            "Submit audited financials to unlock reconciliation"
        )
    data_source_pills.append({"label": "CRB · not submitted", "active": False})
    data_source_pills.append({"label": "Identity · not submitted", "active": False})

    total_txn_count = len(txns)

    # ── Key metrics (4 cells, different per state) ───────────────────────────
    if recon_available:
        turnover_cents = int(af.get("turnover_cents") or 0)
        pbt_cents      = int(af.get("profit_before_tax_cents") or 0)
        pbt_margin     = (pbt_cents / turnover_cents * 100) if turnover_cents > 0 else 0

        loans_r = recon_section.get("loan_activity") or {}
        loan_var_pct = loans_r.get("variance_pct")
        loan_var_str = (
            f"{abs(loan_var_pct):.1f}% var" if loan_var_pct is not None else "0% var"
        )

        rev_r    = recon_section.get("revenue") or {}
        rev_gap  = rev_r.get("gap_pct")
        rev_gap_str = f"{rev_gap:.1f}%" if rev_gap is not None else "--"

        kms = [
            {
                "label": "Avg monthly revenue",
                "value": _fmt_kes_compact(avg_rev_cents),
                "sub":   f"{currency} · operational inflows",
                "color_class": "",
            },
            {
                "label": "PBT margin",
                "value": f"{pbt_margin:.2f}%",
                "sub":   f"vs declared turnover · FY{fy}",
                "color_class": "positive" if pbt_margin > 0 else "negative",
            },
            {
                "label": "Loan reconciliation",
                "value": loan_var_str,
                "sub":   f"{loans_r.get('status', '')} · Note 14",
                "color_class": "warning",
            },
            {
                "label": "Revenue gap",
                "value": rev_gap_str,
                "sub":   "observed vs declared · accrual basis",
                "color_class": "warning" if (rev_gap or 0) > 15 else "",
            },
        ]
    else:
        kms = [
            {
                "label": "Avg monthly revenue",
                "value": _fmt_kes_compact(avg_rev_cents),
                "sub":   f"{currency} · operational inflows",
                "color_class": "",
            },
            {
                "label": "Income quality",
                "value": f"{income_quality_pct:.1f}%",
                "sub":   "operational vs total inflows",
                "color_class": "positive" if income_quality_pct >= 70 else "warning",
            },
            {
                "label": "Loan obligations",
                "value": f"{loan_freq:.1f}/mo",
                "sub":   f"repayments · {loan_repayment_txn_count} txns detected",
                "color_class": "warning",
            },
            {
                "label": "Cash trend",
                "value": cash_trend_str,
                "sub":   cash_trend_sub,
                "color_class": "positive" if cash_trend_str.startswith("+") else "warning",
            },
        ]

    # ── Monthly cashflow chart rows ──────────────────────────────────────────
    active_months = period_months
    max_abs_net = (
        max(abs(monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"])
            for m in active_months)
        if active_months else 1
    ) or 1

    cashflow_rows_ctx = []
    for m in active_months:
        v = monthly_merged[m]
        net     = v["inflow_cents"] - v["outflow_cents"]
        abs_net = abs(net)
        bar_pct = min(int(abs_net / max_abs_net * 100), 100)
        sign    = "+" if net >= 0 else "−"
        cashflow_rows_ctx.append({
            "month_label":    MONTH_ABBR.get(m[5:7], m[5:7]),
            "inflow_str":     f"{v['inflow_cents'] / 100:,.0f}",
            "outflow_str":    f"{v['outflow_cents'] / 100:,.0f}",
            "net_str":        f"{sign}{abs_net / 100:,.0f}",
            "net_color_class": "pos" if net >= 0 else "neg",
            "positive":       net >= 0,
            "bar_pct":        bar_pct,
        })

    # ── Composition segments ─────────────────────────────────────────────────
    _in_groups  = [("revenue_operational", "pesalink_inflow"), ("mpesa_inflow",), ("transfer",)]
    _in_labels  = ["Bank transfers / invoiced", "M-Pesa channel", "Inter-account"]
    _in_colors  = ["#0D9488", "#6366F1", "#F59E0B"]

    inflow_segments = []
    in_accounted = 0
    for roles, label, color in zip(_in_groups, _in_labels, _in_colors):
        total = sum(by_role_in.get(r, 0) for r in roles)
        if total > 0 and total_in > 0:
            pct = max(1, int(total / total_in * 100))
            in_accounted += pct
            inflow_segments.append({
                "label": label, "pct": pct, "color": color,
                "amount_str": _fmt_kes_millions(total),
            })
    other_in = total_in - sum(by_role_in.get(r, 0) for grp in _in_groups for r in grp)
    if other_in > 0 and total_in > 0:
        inflow_segments.append({
            "label": "Other / unclassified",
            "pct": max(0, 100 - in_accounted),
            "color": "#D1D5DB",
            "amount_str": _fmt_kes_millions(other_in),
        })

    _out_groups = [
        ("supplier", "supplier_payment"),
        ("operational", "operational_payment"),
        ("payroll",),
        ("loan_repayment",),
        ("tax_payment",),
    ]
    _out_labels = ["Procurement / COGS", "Operational", "Payroll", "Loan repayments", "Tax (KRA)"]
    _out_colors = ["#1C2135", "#B45309", "#4338CA", "#0D9488", "#B91C1C"]

    outflow_segments = []
    out_accounted = 0
    for roles, label, color in zip(_out_groups, _out_labels, _out_colors):
        total = sum(by_role_out.get(r, 0) for r in roles)
        if total > 0 and total_out > 0:
            pct = max(1, int(total / total_out * 100))
            out_accounted += pct
            outflow_segments.append({
                "label": label, "pct": pct, "color": color,
                "amount_str": _fmt_kes_millions(total),
            })
    other_out = total_out - sum(by_role_out.get(r, 0) for grp in _out_groups for r in grp)
    if other_out > 0 and total_out > 0:
        outflow_segments.append({
            "label": "Finance charges / other",
            "pct": max(0, 100 - out_accounted),
            "color": "#D1D5DB",
            "amount_str": _fmt_kes_millions(other_out),
        })

    # Composition warn strings
    mpesa_cents = by_role_in.get("mpesa_inflow", 0)
    mpesa_pct   = (mpesa_cents / total_in * 100) if total_in else 0
    mpesa_txn_count = sum(1 for t in canon_tagged if t["role"] == "mpesa_inflow" and t["amount_cents"] > 0)
    mpesa_avg = (mpesa_cents / mpesa_txn_count / 100) if mpesa_txn_count > 0 else 0
    inflow_warn = (
        f"M-Pesa at {mpesa_txn_count:,} transactions (avg {currency} {mpesa_avg:,.0f} per txn) · "
        "verify consistency with declared business model and customer type · pattern observed, not concluded"
    ) if mpesa_pct > 25 else ""

    procurement_cents = sum(by_role_out.get(r, 0) for r in ("supplier", "supplier_payment"))
    procurement_pct   = (procurement_cents / total_out * 100) if total_out else 0
    outflow_warn = (
        f"Procurement outflows ({procurement_pct:.0f}%) — cash procurement controls and cross-border "
        "documentation should be verified · observed supplier payments represent partial COGS visibility"
    ) if procurement_pct > 50 else ""

    # ── Supplier Payment Analysis (PAR-63) ────────────────────────────────────
    # Same role set as procurement_cents above, but broken out per counterparty
    # entity (not just a role-level total) so a top-supplier concentration
    # figure can be surfaced. Renders in both recon_available states — this
    # depends only on live transaction/entity data, not audited financials.
    _SUPPLIER_ROLES = ("supplier", "supplier_payment")
    # PAR-89 used 30 transactions as the minimum sample before trusting a
    # per-deal statistic (median/MAD), falling back to a flat default below
    # that — see classifier.py's _MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD. Same
    # cutoff, same reasoning, applied here to supplier_txn_count specifically
    # (the actual sample the concentration % is drawn from) rather than total
    # deal transactions: a concentration % computed over a handful of supplier
    # transactions is not a stable finding — at N=1 it is mathematically
    # guaranteed to read 100%, regardless of the business's real supplier mix.
    _MIN_SUPPLIER_SAMPLE_SIZE = 30
    supplier_by_entity: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "count": 0})
    for t in txns:
        if t["role"] in _SUPPLIER_ROLES and t["signed"] < 0:
            eid = t.get("entity_id") or ""
            supplier_by_entity[eid]["total"] += t["abs"]
            supplier_by_entity[eid]["count"] += 1

    supplier_total_cents  = sum(v["total"] for v in supplier_by_entity.values())
    supplier_txn_count    = sum(v["count"] for v in supplier_by_entity.values())
    supplier_entity_count = len(supplier_by_entity)

    if supplier_by_entity and supplier_total_cents > 0:
        top_eid, top_data = max(supplier_by_entity.items(), key=lambda kv: kv[1]["total"])
        top_supplier_name = (
            entity_name_by_id.get(top_eid)
            or (top_eid[:16] + "…" if len(top_eid) > 16 else top_eid)
            or "--"
        )
        top_supplier_pct = top_data["total"] / supplier_total_cents * 100

        if supplier_txn_count < _MIN_SUPPLIER_SAMPLE_SIZE:
            supplier_concentration_clause = (
                f"Insufficient supplier transaction volume for a reliable "
                f"concentration assessment (N={supplier_txn_count})."
            )
        else:
            # Thresholds mirror the >30% "HIGH concentration" convention
            # PARITY_SCIENCE.md Part III defines for Customer Concentration —
            # reused here for the supplier side by analogy, not independently
            # codified for suppliers. BORROWED THRESHOLD, PENDING FORMAL
            # PARITY SCIENCE SIGN-OFF — see PAR-63_new_sections_spec.md
            # Section 2 and the PR description's open-items list. Needs its
            # own Part III Supplier Concentration pattern entry (Signal/
            # Confidence/Action) before being treated as a settled rule.
            if top_supplier_pct >= 30:
                supplier_concentration_clause = "This represents HIGH supplier concentration risk."
            elif top_supplier_pct >= 15:
                supplier_concentration_clause = "This represents MODERATE supplier concentration."
            else:
                supplier_concentration_clause = "Supplier spend is well-diversified across counterparties."

        supplier_payments_ctx: Dict[str, Any] = {
            "available":    True,
            "total_str":    _fmt_kes(supplier_total_cents),
            "txn_count":    supplier_txn_count,
            "entity_count": supplier_entity_count,
            "top_name":     top_supplier_name,
            "top_pct_str":  f"{top_supplier_pct:.1f}%",
            "clause":       supplier_concentration_clause,
        }
    else:
        supplier_payments_ctx = {"available": False}

    # ── Transaction Pattern Analysis (PAR-63) ─────────────────────────────────
    # tx["anomalies"] is computed by anomaly_detector.py during run_pipeline()
    # and mutated onto the same raw transaction dicts that flow through to
    # build_pds_payload() — it's sealed into canonical_json.transactions[] but
    # never written to any DB column, so it can ONLY be read from
    # canonical_json, not from the live pds_raw_transactions fetch (txns).
    # Both the anomaly aggregation AND the total-transaction denominator below
    # are read from the SAME raw canonical.get("transactions") list, in a
    # single pass — deliberately not canon_tagged (which silently drops any
    # row missing a txn_date, line ~230 above) or total_txn_count (which is
    # len(txns), the live-fetch count) — to avoid the exact numerator/
    # denominator cross-source mismatch caught in Tax Compliance Analysis
    # (PR #110 review). Legacy snapshots sealed before anomaly_detector.py
    # existed simply have no "anomalies" key per transaction — treated as an
    # empty list, not an error.
    _SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
    canon_raw_transactions = canonical.get("transactions") or []
    total_txn_count_canon = len(canon_raw_transactions)

    all_anomalies: List[Dict[str, Any]] = []
    for t in canon_raw_transactions:
        for a in (t.get("anomalies") or []):
            all_anomalies.append({
                "type":     a.get("type") or "UNKNOWN",
                "severity": a.get("severity") or "LOW",
                "reason":   a.get("reason") or "",
                "abs_amount_cents": abs(int(t.get("signed_amount_cents") or 0)),
                "txn_date": t.get("txn_date") or "",
            })

    total_flagged  = len(all_anomalies)
    critical_count = sum(1 for a in all_anomalies if a["severity"] == "CRITICAL")
    high_count     = sum(1 for a in all_anomalies if a["severity"] == "HIGH")

    if all_anomalies:
        top_anomaly = max(
            all_anomalies,
            key=lambda a: (_SEVERITY_RANK.get(a["severity"], 0), a["abs_amount_cents"]),
        )
    else:
        top_anomaly = None

    if top_anomaly and top_anomaly["severity"] in ("CRITICAL", "HIGH"):
        top_pattern_clause = (
            f"The most significant: a {top_anomaly['type']} of "
            f"{_fmt_kes(top_anomaly['abs_amount_cents'])} on {top_anomaly['txn_date']} "
            f"({top_anomaly['reason']})."
        )
    else:
        top_pattern_clause = "No high-severity transaction patterns were detected."

    transaction_patterns_ctx: Dict[str, Any] = {
        "critical_count":  critical_count,
        "high_count":      high_count,
        "total_flagged":   total_flagged,
        "total_txn_count": total_txn_count_canon,
        "clause":          top_pattern_clause,
    }

    # ── Tax Compliance Analysis (PAR-63) ──────────────────────────────────────
    # Live recompute over the same txns list already in scope for this render
    # — NOT the cached pds_documents.analytics.credit_scoring_inputs blob
    # (credit_scoring_inputs_list above). A stale cache silently drifting
    # after an analyst override or reprocessing is exactly the "wrong answer
    # without an error" risk PARITY_SCIENCE.md flags for an investor-facing
    # compliance conclusion. Mirrors the by_month_rev/procurement_cents
    # aggregation pattern already used in this file — no new query, no new
    # style. Renders in both recon_available states — depends only on live
    # transaction data.
    _TAX_ROLES = ("tax_payment", "kra_payment")
    tax_months_active: set = set()
    tax_total_cents_active = 0
    # Denominator must come from the same txns list as the numerator above —
    # period_months (used elsewhere in this file) is derived from
    # monthly_merged/canon_tagged, which is sourced from canonical_json, not
    # from txns. Mixing the two would compute a ratio whose numerator and
    # denominator disagree on which data source is authoritative, silently
    # defeating the whole point of live-recomputing this section instead of
    # trusting a cache. See PAR-63 PR #110 review — caught before merge.
    #
    # PAR-100: payroll_months_active piggybacks on this same single pass so
    # the "Irregular payroll" Observed Pattern card below (~line 1030) can
    # share n_total_months as its denominator too, instead of pairing a
    # cached pds_documents.analytics.credit_scoring_inputs numerator
    # (populated once at ingestion, never refreshed) with this file's live
    # period — the exact numerator/denominator cross-source split this
    # section was already rebuilt to avoid for tax compliance.
    all_months_active: set = set()
    payroll_months_active: set = set()
    for t in txns:
        m = (t["txn_date"] or "")[:7]
        if t["txn_date"] and _in_active_period(m):
            all_months_active.add(m)
            if t["role"] in _TAX_ROLES and t["signed"] < 0:
                tax_months_active.add(m)
                tax_total_cents_active += t["abs"]
            if t["role"] == "payroll":
                payroll_months_active.add(m)

    n_tax_months   = len(tax_months_active)
    n_total_months = len(all_months_active)
    n_payroll_months = len(payroll_months_active)

    # Mirrors backend/v1/analytics.py::credit_scoring_inputs()'s own
    # payroll_stability thresholds (consistent/mostly-consistent/irregular
    # cutoffs) — same classification, recomputed live over this render's
    # txns/active-period instead of read from the stale cached blob.
    if n_total_months == 0 or n_payroll_months == 0:
        payroll_stability_live = "NOT_DETECTED"
    elif n_payroll_months == n_total_months:
        payroll_stability_live = "CONSISTENT"
    elif n_payroll_months >= n_total_months * 8 // 10:
        payroll_stability_live = "MOSTLY_CONSISTENT"
    else:
        payroll_stability_live = "IRREGULAR"

    if n_total_months == 0:
        kra_compliance = "NOT_DETECTED"
    elif n_tax_months >= n_total_months * 0.8:
        kra_compliance = "COMPLIANT"
    elif n_tax_months > 0:
        kra_compliance = "PARTIAL"
    else:
        kra_compliance = "NOT_DETECTED"

    if kra_compliance == "COMPLIANT":
        tax_compliance_clause = "Tax payment pattern is consistent with the business's stated activity level."
    elif kra_compliance == "PARTIAL":
        tax_compliance_clause = "Partial tax payment pattern — verify against filed returns."
    else:
        tax_compliance_clause = (
            "No tax payments detected in bank activity. This does not necessarily "
            "indicate non-compliance — tax may be paid from an account outside this "
            "statement set, or by a third party. Verify against a KRA compliance certificate."
        )

    tax_compliance_ctx: Dict[str, Any] = {
        "total_str":      _fmt_kes(tax_total_cents_active),
        "n_tax_months":   n_tax_months,
        "n_total_months": n_total_months,
        "kra_compliance": kra_compliance,
        "clause":         tax_compliance_clause,
    }

    # ── Inter-Account Transfer Analysis (PAR-63; live-checked per PAR-102) ───
    # Self-transfer/cash-sweep detection between a company's own bank accounts
    # depends on transfer_matcher.match_transfers() pairing transactions across
    # DIFFERENT accounts, which requires per-transaction account_id tagging.
    # PAR-102 fixed that tagging (str(document_id) per source document) for
    # deals ingested after commit 64bebd4, but older/still-broken deals still
    # resolve every transaction to the same undifferentiated account value.
    # This section now checks pds_transfer_links directly rather than
    # asserting the old blanket "not available" for every deal:
    #   - real transfer_links rows exist       -> render the real breakdown
    #   - zero rows AND 2+ distinct account_id  -> detection ran, genuine zero
    #   - zero rows AND <2 distinct account_id  -> honest limitation stub
    #     (unchanged copy — still accurate for any deal whose account_id
    #     tagging is still broken)
    _TRANSFER_ROLES = ("transfer", "internal_transfer")
    manual_transfer_count = sum(1 for t in txns if t["role"] in _TRANSFER_ROLES)

    if manual_transfer_count > 0:
        transfer_override_note = (
            f"{manual_transfer_count} transaction(s) were manually flagged by an analyst "
            "as self-transfers via override — see the Overrides section. This is "
            "analyst-asserted, not system-detected, and does not reflect automatic "
            "self-transfer/cash-sweep detection."
        )
    else:
        transfer_override_note = "No transactions have been manually flagged as self-transfers for this deal."

    transfer_link_rows = (
        sb.table("pds_transfer_links")
        .select("txn_out_id, txn_in_id, abs_amount_cents")
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    document_id_by_txn: Dict[str, Optional[str]] = {t["id"]: t.get("document_id") for t in txn_rows}
    distinct_account_ids = {t.get("account_id") for t in txn_rows if t.get("account_id")}

    def _account_label(txn_id: str, fallback: str) -> str:
        doc_id = document_id_by_txn.get(txn_id)
        return doc_bank_by_id.get(doc_id) or (f"Account {doc_id[:8]}" if doc_id else fallback)

    if transfer_link_rows:
        total_count = len(transfer_link_rows)
        total_cents = sum(l["abs_amount_cents"] for l in transfer_link_rows)
        pair_agg: Dict[str, Dict[str, int]] = defaultdict(lambda: {"count": 0, "cents": 0})
        for link in transfer_link_rows:
            out_label = _account_label(link["txn_out_id"], "Account A")
            in_label  = _account_label(link["txn_in_id"], "Account B")
            key = f"{out_label} -> {in_label}"
            pair_agg[key]["count"] += 1
            pair_agg[key]["cents"] += link["abs_amount_cents"]
        transfer_pairs = [
            {"label": key, "count": agg["count"], "total_str": _fmt_kes(agg["cents"])}
            for key, agg in sorted(pair_agg.items())
        ]
        inter_account_transfer_note = (
            f"{total_count} inter-account transfer pair(s) detected between this company's own "
            f"bank accounts, totaling {_fmt_kes(total_cents)}. Detected automatically by pairing "
            "same-amount, opposite-sign transactions across different accounts within a short "
            "window — see the breakdown above."
        )
        inter_account_badge = "Detected"
    elif len(distinct_account_ids) >= 2:
        transfer_pairs = []
        inter_account_transfer_note = (
            "Self-transfer / cash-sweep detection ran for this deal — transactions are tagged "
            "with distinct per-account identifiers — and found no qualifying inter-account "
            "transfer pairs in this period. This is a genuine result, not an infrastructure gap."
        )
        inter_account_badge = "No Transfers Found"
    else:
        transfer_pairs = []
        inter_account_transfer_note = (
            "Self-transfer / cash-sweep analysis between this company's own bank accounts "
            "is not currently available. Detection depends on each transaction being tagged "
            "with the specific account it belongs to, and that per-account tagging is not "
            "yet populated correctly in the current ingestion pipeline — every transaction "
            "currently resolves to the same undifferentiated account value, so the matching "
            "logic cannot distinguish between a company's own accounts. This is a known "
            "infrastructure gap, not a finding that no such transfers exist."
        )
        inter_account_badge = "Not Available"

    inter_account_transfer_ctx: Dict[str, Any] = {
        "badge_label": inter_account_badge,
        "pairs": transfer_pairs,
        "note": inter_account_transfer_note,
        "override_note": transfer_override_note,
    }

    # ── Tax ───────────────────────────────────────────────────────────────────
    tax_freq_str  = (
        f"{len(tax_txns) / tax_months_count:.1f} / month" if tax_months_count > 0 else "--"
    )
    tax_jan_spike_str = _fmt_kes(jan_total) if jan_total > 0 else ""
    if jan_spike and penalty_count == 0:
        tax_note = (
            "Consistent KRA cadence observed across all months. "
            "January spike consistent with prior-year settlement — not a penalty indicator. "
            "Regular PAYE + VAT cadence maintained. "
            "Note: Bank payment regularity observed, not compliance status. Verify certificate independently."
        )
    elif penalty_count > 0:
        tax_note = (
            f"{penalty_count} potential penalty transaction(s) detected — "
            "verify KRA compliance certificate independently."
        )
    else:
        tax_note = (
            "Regular KRA payment pattern observed. "
            "Note: Bank regularity only — verify compliance certificate independently."
        )

    # ── Pattern cards ─────────────────────────────────────────────────────────
    _TAG_CLASS  = {"Watch": "t-wat", "Observed": "t-chk", "Pattern": "t-pat", "Coverage": "t-chk"}
    _ITEM_CLASS = {"Watch": "watch", "Observed": "check", "Pattern": "pattern", "Coverage": "check"}

    patterns: List[Dict] = []

    if mpesa_pct > 40:
        tag = "Watch"
        patterns.append({
            "name": "M-Pesa concentration",
            "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"M-Pesa inflows represent {mpesa_pct:.1f}% of total observed inflows",
            "check_prompt": "→ Review: consistent with declared customer mix and B2B model?",
        })

    for cs in credit_scoring_inputs_list:
        if cs.get("kra_compliance") == "GAPS_DETECTED":
            tag = "Observed"
            patterns.append({
                "name": "Tax payment gap",
                "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
                "data_statement": cs.get("kra_note") or "Tax payment gaps detected",
                "check_prompt": "→ Review: gap months explained by filing schedule or missed payments?",
            })
            break

    # PAR-100: payroll_stability_live/n_payroll_months/n_total_months are all
    # computed above from the single live pass over txns (same block as Tax
    # Compliance Analysis) — no cached credit_scoring_inputs field used here.
    if payroll_stability_live == "IRREGULAR":
        tag = "Pattern"
        patterns.append({
            "name": "Irregular payroll",
            "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"Payroll detected in {n_payroll_months} of {n_total_months} months",
            "check_prompt": "→ Review: casual workforce or payroll routed off-statement?",
        })

    if len(neg_months) > 2:
        label_months = ", ".join(
            MONTH_ABBR.get(m[5:7], m[5:7]) for m in neg_months[:3]
        ) + ("..." if len(neg_months) > 3 else "")
        tag = "Pattern"
        patterns.append({
            "name": "Net-negative months",
            "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"{len(neg_months)} of {len(period_months)} months net-negative: {label_months}",
            "check_prompt": "→ Review: seasonal pattern or sustained cash drain?",
        })

    if needs_review_count > 100:
        tag = "Coverage"
        patterns.append({
            "name": "Analyst classification pending",
            "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"{needs_review_count} transactions flagged needs_review",
            "check_prompt": "→ Review: resolve in Parity dashboard before finalising snapshot.",
        })

    patterns = patterns[:5]

    # ── Reconciliation rows (recon state only) ───────────────────────────────
    recon_rows: List[Dict] = []
    recon_fiscal_note = ""

    # Coverage-aware badge softening: a variance is only treated as a genuine,
    # unexplained red b-variance when bank statement coverage is complete.
    # When accounts are known to be missing, the same underlying variance is
    # surfaced as an explainable amber b-warn naming the actual missing
    # account(s) — derived from the real coverage data, not hardcoded to any
    # one deal, so this calibration applies correctly to every deal on render.
    missing_bank_names = [
        a.get("bank_name") for a in (acct_cov_raw.get("account_details") or [])
        if a.get("status") != "SUBMITTED" and a.get("bank_name")
    ]
    coverage_incomplete = recon_available and bool(missing_bank_names)
    missing_note = (
        f"Coverage gap — {', '.join(missing_bank_names)} not submitted."
        if coverage_incomplete else ""
    )

    if recon_available:
        cash_r = recon_section.get("cash_position") or {}
        rev_r  = recon_section.get("revenue") or {}
        exp_r  = recon_section.get("expenses") or {}
        loan_r = recon_section.get("loan_activity") or {}

        # Derive fiscal note from sub-section
        fp = rev_r.get("fiscal_period") or ""
        if " to " in fp:
            end_date = fp.split(" to ")[-1]
            recon_fiscal_note = f"All checks at fiscal year-end {end_date}"
        elif fy:
            recon_fiscal_note = f"All checks at fiscal year-end Dec 31 {fy}"

        # Cash position — never softened by coverage gaps: the declared Note 11
        # balance is the company's own attestation of total cash at year-end, so
        # a variance here is treated as genuinely unexplained regardless of which
        # bank statements are missing.
        cash_var    = cash_r.get("variance_pct")
        cash_status = cash_r.get("status") or "SKIPPED"
        cash_badge  = _status_to_badge(cash_status)
        if cash_status == "EXACT_MATCH":
            cash_assessment = "On submitted accounts: KES 0 variance."
        elif cash_var is not None:
            cash_assessment = f"{abs(cash_var):.1f}% variance on submitted accounts."
        else:
            cash_assessment = cash_r.get("reason") or "Insufficient data."
        recon_rows.append({
            "check":          "Cash position",
            "observed_str":   _fmt_kes(int(cash_r.get("total_bank_kes", 0) * 100)),
            "observed_sub":   "Bank accounts at fiscal year-end",
            "declared_str":   _fmt_kes(int(cash_r.get("total_declared_kes", 0) * 100)),
            "declared_sub":   "Note 11 · cash and equivalents",
            "variance_str":   f"{cash_var:.1f}%" if cash_var is not None else "--",
            "variance_class": _BADGE_VARIANCE_CLASS[cash_badge[0]],
            "badge_class":    cash_badge[0],
            "badge_label":    cash_badge[1],
            "assessment":     cash_assessment,
        })

        # Revenue
        rev_gap  = rev_r.get("gap_pct")
        rev_text = rev_r.get("assessment") or ""
        rev_status = (
            "HEALTHY" if "HEALTHY" in rev_text
            else ("ACCEPTABLE" if "WARNING" not in rev_text and "RISK" not in rev_text else "VARIANCE")
        )
        rev_badge = _status_to_badge(rev_status, coverage_incomplete)
        rev_assessment = rev_text or "--"
        if rev_badge[0] == "b-warn":
            rev_assessment = f"{rev_assessment.rstrip('.')} {missing_note}"
        recon_rows.append({
            "check":        "Revenue",
            "observed_str": _fmt_kes(int(rev_r.get("bank_inflows_kes", 0) * 100)),
            "observed_sub": "Net operational inflows",
            "declared_str": _fmt_kes(int(rev_r.get("declared_revenue_kes", 0) * 100)),
            "declared_sub": "Declared turnover",
            "variance_str": f"{rev_gap:.1f}% gap" if rev_gap is not None else "--",
            "variance_class": _BADGE_VARIANCE_CLASS[rev_badge[0]],
            "badge_class":  rev_badge[0],
            "badge_label":  rev_badge[1],
            "assessment":   rev_assessment,
        })

        # Expenses
        exp_gap   = exp_r.get("gap_pct")
        exp_badge = _status_to_badge("ACCEPTABLE" if abs(exp_gap or 0) <= 15 else "VARIANCE", coverage_incomplete)
        exp_assessment = exp_r.get("explanation") or "--"
        if exp_badge[0] == "b-warn":
            exp_assessment = f"{exp_assessment.rstrip('.')} {missing_note}"
        recon_rows.append({
            "check":        "Expenses",
            "observed_str": _fmt_kes(int(exp_r.get("bank_outflows_kes", 0) * 100)),
            "observed_sub": "Net operational outflows",
            "declared_str": _fmt_kes(int(exp_r.get("declared_expenses_kes", 0) * 100)),
            "declared_sub": "Total declared expenses",
            "variance_str": f"{exp_gap:.1f}% gap" if exp_gap is not None else "--",
            "variance_class": _BADGE_VARIANCE_CLASS[exp_badge[0]],
            "badge_class":  exp_badge[0],
            "badge_label":  exp_badge[1],
            "assessment":   exp_assessment,
        })

        # Loan activity
        loan_var    = loan_r.get("variance_pct")
        loan_status = loan_r.get("status") or "VARIANCE"
        loan_badge  = _status_to_badge(loan_status, coverage_incomplete)
        if loan_status == "EXACT_MATCH":
            loan_assessment = "Net borrowing matches cashflow statement exactly."
        elif loan_var is not None:
            loan_assessment = f"{abs(loan_var):.1f}% variance — review facility discrepancy."
        else:
            loan_assessment = loan_r.get("reason") or "Insufficient data."
        if loan_badge[0] == "b-warn":
            loan_assessment = f"{loan_assessment.rstrip('.')} {missing_note}"
        recon_rows.append({
            "check":        "Loan activity",
            "observed_str": _fmt_kes(int(loan_r.get("bank_net_borrowing_kes", 0) * 100)),
            "observed_sub": "Net borrowings · bank-detected",
            "declared_str": _fmt_kes(int(loan_r.get("declared_net_borrowing_kes", 0) * 100)),
            "declared_sub": "Cashflow statement · Note 14",
            "variance_str": f"{loan_var:.1f}%" if loan_var is not None else "0%",
            "variance_class": _BADGE_VARIANCE_CLASS[loan_badge[0]],
            "badge_class":  loan_badge[0],
            "badge_label":  loan_badge[1],
            "assessment":   loan_assessment,
        })

    # ── Loan facilities table (recon state) ──────────────────────────────────
    loans_r        = (recon_section.get("loan_activity") or {}) if recon_available else {}
    loan_recon_status = loans_r.get("status") or ""
    fac_match_class, fac_match_label = _status_to_badge(loan_recon_status or "VARIANCE", coverage_incomplete)
    loan_facilities = [
        {
            "name":        fac.get("name") or "--",
            "amount_str":  _fmt_kes(fac.get("amount_cents") or 0),
            "match_class": fac_match_class,
            "match_label": fac_match_label,
        }
        for fac in (af.get("loan_breakdown") or [])
    ]

    loan_bank_net_str     = _fmt_kes(int(loans_r.get("bank_net_borrowing_kes", 0) * 100))
    loan_declared_net_str = _fmt_kes(int(loans_r.get("declared_net_borrowing_kes", 0) * 100))
    loan_var_raw          = loans_r.get("variance_pct")
    loan_variance_str     = f"{loan_var_raw:.1f}%" if loan_var_raw is not None else "0%"

    # ── Inventory Analysis (PAR-63, recon state only) ────────────────────────
    # Single fiscal-year audited-financials figure, not a monthly time series.
    # turnover = cost_of_sales_cents / inventory_cents; DIO = 365 / turnover.
    inv_fy = str(af.get("financial_year") or "") if recon_available else ""
    inventory_cents_raw     = af.get("inventory_cents") if recon_available else None
    cost_of_sales_cents_raw = af.get("cost_of_sales_cents") if recon_available else None
    extraction_confidence_raw = af.get("extraction_confidence") if recon_available else None

    inventory_data_present = (
        recon_available
        and inventory_cents_raw is not None
        and cost_of_sales_cents_raw is not None
        and int(inventory_cents_raw) > 0
    )
    if inventory_data_present:
        inventory_cents     = int(inventory_cents_raw)
        cost_of_sales_cents = int(cost_of_sales_cents_raw)
        inventory_turnover   = cost_of_sales_cents / inventory_cents
        dio_days             = 365 / inventory_turnover if inventory_turnover > 0 else None
        if inventory_turnover >= 6:
            inventory_clause = "Inventory turns over quickly relative to cost of sales — LOW inventory risk."
        elif inventory_turnover >= 3:
            inventory_clause = "Inventory turnover is moderate."
        else:
            inventory_clause = (
                "Inventory turns over slowly — may indicate slow-moving stock or "
                "overstocking risk."
            )
        inventory_ctx: Dict[str, Any] = {
            "available":      True,
            "financial_year": inv_fy,
            "inventory_str":  _fmt_kes(inventory_cents),
            "cogs_str":       _fmt_kes(cost_of_sales_cents),
            "turnover_str":   f"{inventory_turnover:.1f}x",
            "dio_str":        f"{dio_days:.0f} days" if dio_days is not None else "--",
            "clause":         inventory_clause,
            "confidence_str": (
                f"{extraction_confidence_raw:.2f}" if extraction_confidence_raw is not None else "not recorded"
            ),
        }
    else:
        inventory_ctx = {
            "available": False,
            "financial_year": inv_fy,
            "note": (
                f"Inventory and/or cost of sales figures were not present in the audited "
                f"financial statements provided for FY{inv_fy} — inventory analysis cannot "
                "be computed for this deal."
            ) if recon_available else (
                "Inventory analysis requires audited financials — not yet submitted for this deal."
            ),
        }

    # ── Verify-page summary (reuses figures already computed above) ──────────
    if recon_available:
        loan_recon_label = (loans_r.get("status") or "VARIANCE").replace("_", " ").title()
    else:
        loan_recon_label = "Not reconciled"
    vp_confidence_color = "positive" if recon_tier == "HIGH_CONFIDENCE" else (
        "warning" if recon_tier in ("MEDIUM_CONFIDENCE", "LOW_CONFIDENCE") else ""
    )

    # ── Account coverage section context ─────────────────────────────────────
    _AC_STAT_COLOR = {  # advisory tier → coverage-stat-value modifier
        "NEGLIGIBLE": "ok", "MINOR": "warn", "MATERIAL": "warn", "CRITICAL": "critical",
    }
    _AC_MATERIALITY_PILL = {  # account materiality → status-pill class
        "NEGLIGIBLE": "status-matched", "MINOR": "status-matched",
        "MATERIAL": "status-critical", "CRITICAL": "status-critical",
    }
    if acct_cov_raw.get("coverage_pct") is not None:
        account_coverage_ctx: Dict[str, Any] = {
            "available":        True,
            "coverage_pct":     f"{acct_cov_raw.get('coverage_pct', 0):.1f}",
            "coverage_color_class": _AC_STAT_COLOR.get(acct_cov_raw.get("advisory_tier"), "critical"),
            "declared_count":   acct_cov_raw.get("declared_accounts_count", 0),
            "submitted_count":  acct_cov_raw.get("submitted_accounts_count", 0),
            "missing_count":    acct_cov_raw.get("missing_accounts_count", 0),
            "missing_balance_str": _fmt_kes(int(acct_cov_raw.get("missing_balance_cents") or 0)),
            "advisory_tier":    acct_cov_raw.get("advisory_tier", "--"),
            "recommendation":   acct_cov_raw.get("recommendation", ""),
            "accounts": [
                {
                    "bank_name":    a.get("bank_name") or "--",
                    "declared_str": _fmt_kes(int(a.get("declared_balance_cents") or 0)),
                    "status_label": "✓ Submitted" if a.get("status") == "SUBMITTED" else "Missing",
                    "status_class": "status-matched" if a.get("status") == "SUBMITTED" else "status-missing",
                    "materiality":  a.get("materiality") or "--",
                    "materiality_class": _AC_MATERIALITY_PILL.get(a.get("materiality"), "status-critical"),
                }
                for a in (acct_cov_raw.get("account_details") or [])
            ],
        }
    else:
        account_coverage_ctx = {
            "available": False,
            "note": (
                "Account coverage compares the bank accounts declared in audited "
                "financials (Note 11 cash breakdown) against the statements "
                "submitted. Submit audited financials to populate this advisory."
            ),
        }

    # ── Risk Assessment Summary (PAR-63) ──────────────────────────────────────
    # Reuses existing signals only — tier, account coverage, and the
    # transaction-pattern rollup are all already computed above; this section
    # adds exactly one new computation (revenue concentration by entity).
    #
    # Confirmed Item 2's pds_entities join (entity_name_by_id) still returns
    # correctly before reusing it here — not assumed: the supplier-side tests
    # that depend on the same join (test_supplier_payment_analysis_*) were
    # re-run and still pass unchanged going into this section.
    #
    # largest_rev_pct's numerator AND denominator are both computed from txns
    # (the live pds_raw_transactions fetch) — mirroring exactly how Supplier
    # Payment Analysis computes its concentration. Deliberately NOT mixing in
    # total_in/by_role_in (computed from canon_tagged, i.e. canonical_json) —
    # that would repeat the exact numerator/denominator cross-source mismatch
    # caught in Tax Compliance Analysis (PR #110 review). Same minimum-sample
    # gate as supplier concentration (PAR-89's 30-transaction threshold) for
    # the same reason: a concentration % over a handful of revenue
    # transactions is not a stable finding.
    revenue_by_entity: Dict[str, int] = defaultdict(int)
    revenue_txn_count = 0
    for t in txns:
        if t["role"] in REVENUE_ROLES and t["signed"] > 0:
            eid = t.get("entity_id") or ""
            revenue_by_entity[eid] += t["signed"]
            revenue_txn_count += 1

    revenue_total_cents = sum(revenue_by_entity.values())

    if not revenue_by_entity or revenue_total_cents <= 0:
        largest_rev_pct_str = "--"
    elif revenue_txn_count < _MIN_SUPPLIER_SAMPLE_SIZE:
        largest_rev_pct_str = f"insufficient data (N={revenue_txn_count})"
    else:
        top_rev_eid, top_rev_total = max(revenue_by_entity.items(), key=lambda kv: kv[1])
        largest_rev_pct_str = f"{(top_rev_total / revenue_total_cents * 100):.1f}%"

    risk_critical_count = transaction_patterns_ctx["critical_count"]
    if risk_critical_count > 0:
        risk_anomaly_summary = (
            f"{risk_critical_count} critical transaction-pattern flag(s) were also raised "
            "(see Transaction Pattern Analysis)."
        )
    else:
        risk_anomaly_summary = "No critical transaction-pattern flags were raised."

    # Overall conclusion — restates _compute_tier()'s own existing blocking
    # logic (snapshot_generator.py) in prose, not a new/invented rule. Handles
    # the OBSERVED state (no audited financials at all) as its own case, since
    # the original spec draft only anticipated HIGH/MEDIUM/LOW_CONFIDENCE.
    risk_advisory_tier = account_coverage_ctx.get("advisory_tier", "--") if account_coverage_ctx.get("available") else "--"
    if recon_tier == "OBSERVED":
        risk_conclusion = (
            "This report covers bank-observed data only — audited financials have not been "
            "submitted, so the 4-point reconciliation has not run. Confidence reflects income "
            "quality and cashflow composition indicators only, not a reconciled tier."
        )
    elif recon_tier == "HIGH_CONFIDENCE":
        risk_conclusion = "This deal meets Parity's threshold for high-confidence credit analysis."
    elif recon_tier == "MEDIUM_CONFIDENCE" and risk_advisory_tier == "CRITICAL":
        risk_conclusion = (
            "Confidence is capped at Medium because of a critical account-coverage gap — "
            "resolve missing bank statement coverage before treating this as high-confidence."
        )
    elif recon_tier == "MEDIUM_CONFIDENCE":
        risk_conclusion = (
            "This deal is Medium confidence — cash position or loan activity reconciliation "
            "did not reach exact-match tolerance."
        )
    else:
        risk_conclusion = (
            "This deal is Low confidence — cash position and/or loan activity reconciliation "
            "shows material variance. Manual review is required before credit decisioning."
        )

    # Self-transfer-netting caveat — same known gap as Inter-Account Transfer
    # Analysis, cross-referenced rather than independently re-described, so
    # the two sections don't drift into two different explanations of the
    # same issue. No internal ticket reference in the rendered copy (same
    # rule applied to Item 6's stub).
    risk_transfer_note = (
        "This confidence tier does not yet net out self-transfers between this company's own "
        "bank accounts — see Inter-Account Transfer Analysis above for why that detection "
        "is not currently available."
    )

    risk_assessment_ctx: Dict[str, Any] = {
        "tier":                   recon_tier,
        "advisory_tier":          risk_advisory_tier,
        "missing_pct":            account_coverage_ctx.get("coverage_pct", "--") if account_coverage_ctx.get("available") else "--",
        "largest_rev_pct_str":    largest_rev_pct_str,
        "anomaly_summary":        risk_anomaly_summary,
        "conclusion":             risk_conclusion,
        "transfer_note":          risk_transfer_note,
    }

    # ── Render template ───────────────────────────────────────────────────────
    templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(os.path.abspath(templates_dir)))
    template = env.get_template("snapshot.html")

    context: Dict[str, Any] = {
        "view":               view,
        "partner_name":       partner_name,
        "company_name":       company_name,
        "sector":             "--",
        "period_label":       period_label,
        "generated_date":     generated_date,
        "analyst_notes":      analyst_notes,
        "report_id":          report_id,
        "sha256_hash":        sha256_hash,
        "qr_svg":             qr_svg,
        "verify_url":         verify_url,
        "currency":           currency,
        "recon_available":    recon_available,
        "recon_tier":         recon_tier,
        "vp_confidence_color": vp_confidence_color,
        "loan_recon_label":   loan_recon_label,
        "tier_badge_class":   tier_badge_class,
        "tier_badge_text":    tier_badge_text,
        "data_source_pills":  data_source_pills,
        "data_source_note":   data_source_note,
        "total_txn_count":    total_txn_count,
        "kms":                kms,
        "cashflow_rows":      cashflow_rows_ctx,
        "cashflow_note":      cashflow_note,
        "cashflow_peak_trough_note": cashflow_peak_trough_note,
        "cashflow_trend_note": cashflow_trend_note,
        "inflow_total_str":   _fmt_kes_millions(total_in),
        "inflow_segments":    inflow_segments,
        "inflow_warn":        inflow_warn,
        "outflow_total_str":  _fmt_kes_millions(total_out),
        "outflow_segments":   outflow_segments,
        "outflow_warn":       outflow_warn,
        "tax_count":          len(tax_txns),
        "tax_freq_str":       tax_freq_str,
        "tax_penalty_count":  penalty_count,
        "tax_jan_spike_str":  tax_jan_spike_str,
        "tax_total_str":      _fmt_kes(tax_total_cents),
        "tax_note":           tax_note,
        "loan_disbursed_str": _fmt_kes(loan_disbursed_cents),
        "loan_repaid_str":    _fmt_kes(loan_repaid_cents),
        "loan_net_str":       _fmt_kes(abs(loan_net_cents)),
        "loan_freq_str":      f"{loan_freq:.1f} txns / month",
        "loan_facility_count": loan_repayment_txn_count,
        "loan_facilities":    loan_facilities,
        "loan_recon_status":  loan_recon_status,
        "loan_bank_net_str":  loan_bank_net_str,
        "loan_declared_net_str": loan_declared_net_str,
        "loan_variance_str":  loan_variance_str,
        "recon_rows":         recon_rows,
        "recon_fiscal_note":  recon_fiscal_note,
        "patterns":           patterns,
        "account_coverage":   account_coverage_ctx,
        "inventory":          inventory_ctx,
        "supplier_payments":  supplier_payments_ctx,
        "tax_compliance":     tax_compliance_ctx,
        "transaction_patterns": transaction_patterns_ctx,
        "inter_account_transfer": inter_account_transfer_ctx,
        "risk_assessment":    risk_assessment_ctx,
    }

    return template.render(**context)
