"""
Build rich context from a parsed canonical snapshot for Parity Review AI.

All amounts in the canonical JSON are integer cents; display in KES (÷100).
Growth/burden figures are in basis points (10000 bps = 100%).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ..core.snapshot_engine import decompress_canonical_json_if_needed

logger = logging.getLogger(__name__)

_REVENUE_ROLES       = frozenset({"revenue_operational", "revenue_non_operational"})
_SUPPLIER_ROLES      = frozenset({"supplier_payment"})
_PAYROLL_ROLES       = frozenset({"payroll"})
_LOAN_ROLES          = frozenset({"loan_repayment", "loan_inflow"})
_TAX_ROLES           = frozenset({"tax_payment", "kra_payment"})
_REVIEW_ROLES        = frozenset({"needs_review", "other"})
_NEEDS_REVIEW_ONLY   = frozenset({"needs_review"})


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def parse_snapshot(snapshot_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decompress canonical_json and enrich with pre-computed aggregates.
    Returns a 'deal_data' dict consumed by both context builder and tools.
    """
    raw = decompress_canonical_json_if_needed(snapshot_row["canonical_json"])
    canonical: Dict[str, Any] = json.loads(raw)

    txn_role_map = _build_txn_role_map(canonical)
    entity_names = {
        str(e["entity_id"]): (e.get("display_name") or str(e["entity_id"]))
        for e in canonical.get("entities", [])
    }

    tagged = _tag_transactions(canonical, txn_role_map, entity_names)
    monthly = _compute_monthly_cashflow(canonical)
    entity_breakdown = _compute_entity_breakdown(canonical, txn_role_map)
    metrics = canonical.get("metrics", {})
    csi = canonical.get("credit_scoring_inputs", metrics)  # fallback

    # Top entities by role
    top_suppliers = [r for r in entity_breakdown if r["role"] in _SUPPLIER_ROLES][:10]
    top_revenue   = [r for r in entity_breakdown if r["role"] in _REVENUE_ROLES][:10]
    review_ents   = [r for r in entity_breakdown if r["role"] in _REVIEW_ROLES][:20]

    # Needs-review entity count from snapshot (distinct entities classified needs_review)
    needs_review_entity_count = sum(1 for r in entity_breakdown if r["role"] in _NEEDS_REVIEW_ONLY)

    # Loan repayment total (cents)
    loan_repayment_total = sum(
        abs(t["signed_amount_cents"]) for t in tagged
        if t["role"] == "loan_repayment" and t["signed_amount_cents"] < 0
    )

    # Payroll months
    payroll_months_set = {
        t["txn_date"][:7] for t in tagged
        if t["role"] in _PAYROLL_ROLES and t["txn_date"] and len(t["txn_date"]) >= 7
    }

    # Tax months
    tax_months_set = {
        t["txn_date"][:7] for t in tagged
        if t["role"] in _TAX_ROLES and t["txn_date"] and len(t["txn_date"]) >= 7
    }

    n_months = len({r["month"] for r in monthly}) or 1

    return {
        "canonical": canonical,
        "tagged": tagged,
        "entity_names": entity_names,
        "monthly": monthly,
        "entity_breakdown": entity_breakdown,
        "top_suppliers": top_suppliers,
        "top_revenue": top_revenue,
        "review_ents": review_ents,
        "metrics": metrics,
        "csi": csi,
        "loan_repayment_total_cents": loan_repayment_total,
        "payroll_months": len(payroll_months_set),
        "tax_months": len(tax_months_set),
        "n_months": n_months,
        "currency": canonical.get("currency", "KES"),
        "needs_review_entity_count": needs_review_entity_count,
        # live_needs_review_txns injected by API layer; absent when called outside request context
    }


def build_snapshot_context(deal_data: Dict[str, Any]) -> str:
    """
    Format deal_data into a text block for injection into the AI system prompt.
    """
    csi     = deal_data["csi"]
    metrics = deal_data["metrics"]
    monthly = deal_data["monthly"]
    currency = deal_data["currency"]

    avg_inflow   = int(csi.get("average_monthly_inflow_cents") or metrics.get("average_monthly_inflow_cents") or 0)
    avg_outflow  = int(csi.get("average_monthly_outflow_cents") or metrics.get("average_monthly_outflow_cents") or 0)
    avg_net      = int(csi.get("average_net_monthly_cents") or metrics.get("average_net_monthly_cents") or 0)
    rev_growth_bps = int(csi.get("revenue_growth_bps") or metrics.get("revenue_growth_bps") or 0)
    loan_burden_bps = int(csi.get("loan_repayment_burden_bps") or metrics.get("loan_repayment_burden_bps") or 0)
    payroll_stability = csi.get("payroll_stability") or metrics.get("payroll_stability") or "Unknown"
    payroll_months = deal_data["payroll_months"]
    kra_compliance = csi.get("kra_compliance") or metrics.get("kra_compliance") or "Unknown"
    tax_months = deal_data["tax_months"]
    n_months   = deal_data["n_months"]

    # Total revenue/expenses from tagged transactions
    tagged = deal_data["tagged"]
    total_revenue_cents  = sum(t["signed_amount_cents"] for t in tagged if t["role"] in _REVENUE_ROLES and t["signed_amount_cents"] > 0)
    total_expense_cents  = sum(abs(t["signed_amount_cents"]) for t in tagged if t["signed_amount_cents"] < 0)
    loan_repayment_cents = deal_data["loan_repayment_total_cents"]

    # Debit/credit counts and totals (all transactions, regardless of role)
    credit_txns = [t for t in tagged if t["signed_amount_cents"] > 0]
    debit_txns  = [t for t in tagged if t["signed_amount_cents"] < 0]
    total_credit_cents = sum(t["signed_amount_cents"] for t in credit_txns)
    total_debit_cents  = sum(abs(t["signed_amount_cents"]) for t in debit_txns)

    # Needs-review counts: prefer live transaction count injected by API; fall back to snapshot
    live_txn_count = deal_data.get("live_needs_review_txns")
    snapshot_txn_count = sum(1 for t in tagged if t["role"] in _NEEDS_REVIEW_ONLY)
    review_txn_count = live_txn_count if live_txn_count is not None else snapshot_txn_count
    review_entity_count = deal_data.get("needs_review_entity_count", 0)

    top_suppliers = deal_data["top_suppliers"]
    top_revenue   = deal_data["top_revenue"]
    review_ents   = deal_data["review_ents"]

    def _fmt_kes(cents: int) -> str:
        return f"{currency} {cents / 100:,.0f}"

    def _fmt_entities(rows: List[Dict], limit: int = 5) -> str:
        lines = []
        for i, r in enumerate(rows[:limit], 1):
            pct = r.get("pct_of_category", r.get("pct_of_total", 0))
            lines.append(
                f"{i}. {r['entity_name']}: {_fmt_kes(r['total_abs_cents'])} "
                f"({pct:.1f}% of category, {r['txn_count']} txns)"
            )
        return "\n".join(lines) if lines else "None"

    top_supplier_pct = top_suppliers[0].get("pct_of_category", top_suppliers[0].get("pct_of_total", 0)) if top_suppliers else 0
    top_customer_pct = top_revenue[0].get("pct_of_category", top_revenue[0].get("pct_of_total", 0)) if top_revenue else 0

    return f"""
## DEAL SNAPSHOT CONTEXT

**Period**: {n_months} months of bank statements
**Currency**: {currency}
**Total transactions**: {len(tagged)}

---

## TRANSACTION COUNTS

| Direction | Count | Total Amount |
|-----------|-------|-------------|
| Credits (inflows) | {len(credit_txns)} | {_fmt_kes(total_credit_cents)} |
| Debits (outflows) | {len(debit_txns)} | {_fmt_kes(total_debit_cents)} |
| Net | — | {_fmt_kes(total_credit_cents - total_debit_cents)} |

---

## FINANCIAL SUMMARY

**Revenue (classified operational)**:
- Total: {_fmt_kes(total_revenue_cents)}
- Avg Monthly Inflow: {_fmt_kes(avg_inflow)}
- Revenue Growth (H2 vs H1): {rev_growth_bps / 100:.1f}%

**Expenses**:
- Total: {_fmt_kes(total_expense_cents)}
- Avg Monthly Outflow: {_fmt_kes(avg_outflow)}
- Avg Net Monthly: {_fmt_kes(avg_net)}

**Debt**:
- Loan Repayment Total: {_fmt_kes(loan_repayment_cents)}
- Loan Repayment Burden: {loan_burden_bps / 100:.1f}% of outflows

**Classification**:
- Needs-review: {review_txn_count} transactions across {review_entity_count} distinct entities

---

## TOP SUPPLIERS (by spend)
{_fmt_entities(top_suppliers)}
Top supplier concentration: {top_supplier_pct:.1f}% of all supplier spend

---

## TOP REVENUE SOURCES (by income)
{_fmt_entities(top_revenue)}
Top customer concentration: {top_customer_pct:.1f}% of all revenue

---

## FLAGGED / NEEDS REVIEW ENTITIES (top 5)
{_fmt_entities(review_ents, limit=5)}

---

## COMPLIANCE SIGNALS
- KRA/Tax compliance: {kra_compliance} (payments in {tax_months}/{n_months} months)
- Payroll stability: {payroll_stability} ({payroll_months}/{n_months} months)

---

Available tools:
- get_deal_summary() — transaction counts by direction and role, monthly breakdown, role distribution
- query_transactions(filters) — search individual transactions by role, amount range, entity, date range, anomaly presence. Returns txn_id, date, amount, description, entity.
- calculate_financial_metrics() — DSCR, revenue growth, cash flow volatility, burn rate
- calculate_operational_metrics() — supplier/customer concentration percentages, working capital trend, payroll frequency
- get_entity_details(entity_name) — full transaction history for any entity
- explain_flagged_item(entity_name) — anomaly details for flagged entities
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_txn_role_map(canonical: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(m.get("txn_id", "")): (m.get("role") or "other")
        for m in canonical.get("txn_entity_map", [])
    }


def _tag_transactions(
    canonical: Dict[str, Any],
    txn_role_map: Dict[str, str],
    entity_names: Dict[str, str],
) -> List[Dict[str, Any]]:
    entity_id_map = {
        str(m.get("txn_id", "")): str(m.get("entity_id", ""))
        for m in canonical.get("txn_entity_map", [])
    }
    tagged = []
    for t in canonical.get("transactions", []):
        tid = str(t.get("id") or t.get("txn_id") or "")
        eid = entity_id_map.get(tid, "")
        tagged.append({
            **t,
            "txn_id": tid,
            "role": txn_role_map.get(tid, "other"),
            "entity_id": eid,
            "entity_name": entity_names.get(eid, ""),
            "signed_amount_cents": int(t.get("signed_amount_cents", 0)),
            "txn_date": str(t.get("txn_date") or ""),
        })
    return tagged


def _compute_entity_breakdown(
    canonical: Dict[str, Any],
    txn_role_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    entities_by_id = {
        str(e["entity_id"]): e for e in canonical.get("entities", [])
    }
    txn_amount: Dict[str, int] = {}
    for t in canonical.get("transactions", []):
        amt = int(t.get("signed_amount_cents", 0))
        for key in ("id", "txn_id"):
            tid = str(t.get(key) or "")
            if tid:
                txn_amount[tid] = amt

    agg: Dict[str, Dict[str, Any]] = {}
    for m in canonical.get("txn_entity_map", []):
        eid = str(m.get("entity_id") or "")
        if not eid:
            continue
        tid = str(m.get("txn_id") or "")
        amt = txn_amount.get(tid, 0)
        role = txn_role_map.get(tid, m.get("role") or "other")
        if eid not in agg:
            ent = entities_by_id.get(eid, {})
            agg[eid] = {
                "entity_id": eid,
                "entity_name": ent.get("display_name") or eid[:20],
                "role": role,
                "total_abs_cents": 0,
                "txn_count": 0,
            }
        agg[eid]["total_abs_cents"] += abs(amt)
        agg[eid]["txn_count"] += 1

    rows = list(agg.values())
    # Compute pct_of_category per role group
    role_totals: Dict[str, int] = defaultdict(int)
    for r in rows:
        role_totals[r["role"]] += r["total_abs_cents"]
    for r in rows:
        rt = role_totals[r["role"]]
        r["pct_of_category"] = (r["total_abs_cents"] / rt * 100) if rt > 0 else 0.0
        total = sum(role_totals.values())
        r["pct_of_total"] = (r["total_abs_cents"] / total * 100) if total > 0 else 0.0

    rows.sort(key=lambda r: r["total_abs_cents"], reverse=True)
    return rows


def _compute_monthly_cashflow(canonical: Dict[str, Any]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"inflow": 0, "outflow": 0})
    for t in canonical.get("transactions", []):
        ds = str(t.get("txn_date") or "")
        if len(ds) < 7:
            continue
        amt = int(t.get("signed_amount_cents", 0))
        if amt > 0:
            buckets[ds[:7]]["inflow"] += amt
        else:
            buckets[ds[:7]]["outflow"] += abs(amt)

    rows = []
    for month in sorted(buckets):
        inflow  = buckets[month]["inflow"]
        outflow = buckets[month]["outflow"]
        rows.append({
            "month": month,
            "inflow_cents": inflow,
            "outflow_cents": outflow,
            "net_cents": inflow - outflow,
        })
    return rows
