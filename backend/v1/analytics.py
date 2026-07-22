"""
Parity analytics — deterministic pipeline computations for credit enrichment.

All amounts in integer cents. No floats.
Same input always produces same output.
"""
from __future__ import annotations

from typing import Any

# ── Revenue roles counted in cleaned annual totals ────────────────────────────
_ANNUAL_REVENUE_ROLES = frozenset({
    "revenue_operational",
    "mpesa_inflow",
    "pesalink_inflow",
    "revenue_non_operational",
})

# ── Inflow roles for monthly cashflow ────────────────────────────────────────
_CASHFLOW_INFLOW_ROLES = frozenset({
    "revenue_operational",
    "revenue_non_operational",
    "mpesa_inflow",
    "pesalink_inflow",
    "loan_inflow",
    "capital_injection",
})

# ── Expense roles counted in top-expenses surface ─────────────────────────────
_EXPENSE_ROLES = frozenset({
    "supplier",
    "supplier_payment",
    "payroll",
    "tax_payment",
    "bank_charge",
    "cash_withdrawal",
    "bill_payment",
    "merchant_payment",
})

# Below this absolute prior-month net (cents), a MoM % swing is too noisy to
# be meaningful (e.g. -100% from a near-zero base) — ported from
# parity-ingestion/app/analytics.py::_MOM_RELIABLE_THRESHOLD_CENTS.
_MOM_RELIABLE_THRESHOLD_CENTS = 1_000_000


def _mom_change_bps(prev_net: int, net: int) -> int:
    """Month-on-month change in basis points. Returns 0 if prev_net is zero."""
    if prev_net == 0:
        return 0
    return int((net - prev_net) * 10000 // prev_net)


def annual_revenue_summary(transactions: list[dict]) -> dict:
    """
    Compute cleaned annual revenue totals from classified transactions.

    Excludes: loan_inflow, capital_injection, reversal_credit, transfer, needs_review.
    Revenue roles included: revenue_operational, mpesa_inflow, pesalink_inflow,
    revenue_non_operational.

    Returns integer cents only. No floats.
    """
    by_year: dict[int, int] = {}

    for txn in transactions:
        role = txn.get("role") or txn.get("classification")
        if role not in _ANNUAL_REVENUE_ROLES:
            continue
        amount = txn.get("amount_cents", 0)
        if not isinstance(amount, int):
            raise ValueError(
                f"Non-integer amount_cents: {amount} on txn {txn.get('txn_id')}"
            )
        if amount <= 0:
            continue
        txn_date = txn.get("txn_date", "")
        if not txn_date:
            continue
        try:
            year = int(str(txn_date)[:4])
        except (ValueError, TypeError):
            continue
        by_year[year] = by_year.get(year, 0) + amount

    return {
        "annual_revenue_cents": by_year,
        "years_covered": sorted(by_year.keys()),
        "total_all_years_cents": sum(by_year.values()),
    }


def loan_drawdowns(transactions: list[dict]) -> dict:
    """
    Extract and surface all loan inflow transactions.

    Returns list sorted by date descending, with running total.
    All amounts in integer cents.
    """
    drawdowns: list[dict] = []
    total_cents = 0

    for txn in transactions:
        role = txn.get("role") or txn.get("classification")
        if role != "loan_inflow":
            continue
        amount = txn.get("amount_cents", 0)
        if not isinstance(amount, int):
            raise ValueError(
                f"Non-integer amount_cents on loan txn {txn.get('txn_id')}"
            )
        if amount <= 0:
            continue
        total_cents += amount
        drawdowns.append({
            "txn_date": txn.get("txn_date"),
            "entity_name": txn.get("entity_name") or txn.get("description", "Unknown"),
            "amount_cents": amount,
            "txn_id": txn.get("txn_id"),
        })

    drawdowns.sort(key=lambda x: str(x.get("txn_date", "")), reverse=True)

    return {
        "drawdowns": drawdowns,
        "total_drawdown_cents": total_cents,
        "drawdown_count": len(drawdowns),
    }


def kra_summary(transactions: list[dict]) -> dict:
    """
    Compute KRA tax payment summary.

    Returns: total paid, months with payments, compliance signal.
    All amounts integer cents.
    Compliance: COMPLIANT (payments in >= 10 months), PARTIAL (some), NOT_DETECTED (zero).
    """
    by_month: dict[str, int] = {}
    total_cents = 0
    payments: list[dict] = []

    for txn in transactions:
        role = txn.get("role") or txn.get("classification")
        if role != "tax_payment":
            continue
        amount = txn.get("amount_cents", 0)
        if not isinstance(amount, int):
            raise ValueError(
                f"Non-integer amount_cents on tax txn {txn.get('txn_id')}"
            )
        abs_amount = abs(amount)
        if abs_amount == 0:
            continue
        total_cents += abs_amount
        txn_date = str(txn.get("txn_date", ""))
        month_key = txn_date[:7] if len(txn_date) >= 7 else "unknown"
        by_month[month_key] = by_month.get(month_key, 0) + abs_amount
        payments.append({
            "txn_date": txn.get("txn_date"),
            "entity_name": txn.get("entity_name", "KRA"),
            "amount_cents": abs_amount,
        })

    months_with_payment = len(by_month)

    if months_with_payment == 0:
        compliance = "NOT_DETECTED"
    elif months_with_payment >= 10:
        compliance = "COMPLIANT"
    else:
        compliance = "PARTIAL"

    return {
        "total_tax_cents": total_cents,
        "months_with_payment": months_with_payment,
        "monthly_breakdown": by_month,
        "compliance": compliance,
        "payments": sorted(payments, key=lambda x: str(x.get("txn_date", ""))),
    }


def top_expenses_with_frequency(
    transactions: list[dict],
    top_n: int = 10,
) -> list[dict]:
    """
    Returns top N expense entities by total amount, with transaction frequency.

    Expense roles: supplier, supplier_payment, payroll, tax_payment, bank_charge,
                   cash_withdrawal, bill_payment, merchant_payment.
    All amounts integer cents.
    """
    entity_totals: dict[str, dict[str, Any]] = {}

    for txn in transactions:
        role = txn.get("role") or txn.get("classification")
        if role not in _EXPENSE_ROLES:
            continue
        amount = txn.get("amount_cents", 0)
        if not isinstance(amount, int):
            raise ValueError(
                f"Non-integer amount_cents on expense txn {txn.get('txn_id')}"
            )
        abs_amount = abs(amount)
        if abs_amount == 0:
            continue
        entity = txn.get("entity_name") or txn.get("description", "Unknown")
        if entity not in entity_totals:
            entity_totals[entity] = {"total_cents": 0, "txn_count": 0, "role": role}
        entity_totals[entity]["total_cents"] += abs_amount
        entity_totals[entity]["txn_count"] += 1

    sorted_entities = sorted(
        entity_totals.items(),
        key=lambda x: x[1]["total_cents"],
        reverse=True,
    )

    return [
        {
            "entity_name": name,
            "total_cents": data["total_cents"],
            "txn_count": data["txn_count"],
            "avg_transaction_cents": data["total_cents"] // data["txn_count"],
            "role": data["role"],
        }
        for name, data in sorted_entities[:top_n]
    ]


def credit_scoring_inputs(transactions: list[dict]) -> dict:
    """
    Deal-level Credit Scoring Inputs (Sayuni Capital Section 01), computed from
    classifier `role` (the same source of truth used everywhere else in this
    module) rather than document-level keyword/pattern-hint heuristics.

    Monthly inflow is revenue only (_ANNUAL_REVENUE_ROLES) — excludes loan_inflow
    and capital_injection, matching the original Section 01 definition.
    Loan repayment burden / payroll / KRA use the classifier's own
    loan_repayment / payroll / tax_payment roles instead of keyword matching.
    All amounts integer cents. No floats.
    """
    monthly_in: dict[str, int] = {}
    monthly_out: dict[str, int] = {}
    loan_repayment_total = 0
    total_outflow = 0
    payroll_months: set[str] = set()
    tax_months: set[str] = set()
    tax_total = 0

    for txn in transactions:
        txn_date = str(txn.get("txn_date", ""))
        month = txn_date[:7] if len(txn_date) >= 7 else ""
        if not month:
            continue
        role = txn.get("role") or txn.get("classification") or ""
        amount = txn.get("amount_cents", 0)
        if not isinstance(amount, int):
            raise ValueError(
                f"Non-integer amount_cents: {amount} on txn {txn.get('txn_id')}"
            )

        if role in _ANNUAL_REVENUE_ROLES and amount > 0:
            monthly_in[month] = monthly_in.get(month, 0) + amount

        if amount < 0:
            abs_amount = -amount
            total_outflow += abs_amount
            monthly_out[month] = monthly_out.get(month, 0) + abs_amount

            if role == "loan_repayment":
                loan_repayment_total += abs_amount
            if role == "tax_payment":
                tax_months.add(month)
                tax_total += abs_amount

        if role == "payroll":
            payroll_months.add(month)

    all_months = sorted(monthly_in.keys())
    month_count = len(all_months)
    inflow_values = [monthly_in[m] for m in all_months]

    avg_monthly_inflow = sum(inflow_values) // month_count if month_count else 0

    if inflow_values:
        sorted_vals = sorted(inflow_values)
        n = len(sorted_vals)
        if n % 2 == 1:
            median_monthly_inflow = sorted_vals[n // 2]
        else:
            median_monthly_inflow = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) // 2
    else:
        median_monthly_inflow = 0

    out_values = [monthly_out[m] for m in sorted(monthly_out.keys())]
    avg_monthly_outflow = sum(out_values) // len(out_values) if out_values else 0

    all_period_months = sorted(set(monthly_in.keys()) | set(monthly_out.keys()))
    net_values = [monthly_in.get(m, 0) - monthly_out.get(m, 0) for m in all_period_months]

    avg_net = sum(net_values) // len(net_values) if net_values else 0
    peak_net = max(net_values) if net_values else 0
    trough_net = min(net_values) if net_values else 0

    revenue_growth_bps = 0
    if len(inflow_values) >= 2 and inflow_values[0] > 0:
        revenue_growth_bps = ((inflow_values[-1] - inflow_values[0]) * 10000) // inflow_values[0]

    loan_repayment_burden_bps = 0
    if total_outflow > 0 and loan_repayment_total > 0:
        loan_repayment_burden_bps = (loan_repayment_total * 10000) // total_outflow

    statement_months = len(all_period_months)
    payroll_month_count = len(payroll_months)
    if statement_months == 0 or payroll_month_count == 0:
        payroll_stability = "NOT_DETECTED"
    elif payroll_month_count == statement_months:
        payroll_stability = "CONSISTENT"
    elif payroll_month_count >= statement_months * 8 // 10:
        payroll_stability = "MOSTLY_CONSISTENT"
    else:
        payroll_stability = "IRREGULAR"

    if tax_months:
        tax_gap_months = [m for m in all_period_months if m not in tax_months]
        if not tax_gap_months:
            kra_compliance = "PASS"
            kra_note = f"Tax payments detected in all {len(tax_months)} months"
        else:
            kra_compliance = "GAPS_DETECTED"
            kra_note = f"No tax payment detected in {len(tax_gap_months)} months: {', '.join(tax_gap_months[:3])}"
    else:
        kra_compliance = "NOT_DETECTED"
        kra_note = "No KRA/VAT/PAYE transactions found in statement"

    return {
        "average_monthly_inflow_cents": avg_monthly_inflow,
        "median_monthly_inflow_cents": median_monthly_inflow,
        "average_monthly_outflow_cents": avg_monthly_outflow,
        "average_net_monthly_cents": avg_net,
        "peak_net_position_cents": peak_net,
        "trough_net_position_cents": trough_net,
        "revenue_growth_bps": revenue_growth_bps,
        "loan_repayment_burden_bps": loan_repayment_burden_bps,
        "payroll_stability": payroll_stability,
        "payroll_months_detected": payroll_month_count,
        "kra_compliance": kra_compliance,
        "kra_note": kra_note,
        "tax_total_cents": tax_total,
        "statement_months": statement_months,
        "month_count_with_inflow": month_count,
    }


def monthly_cashflow(transactions: list[dict]) -> list[dict]:
    """
    Month-by-month inflow/outflow/net from classified transactions.

    Inflows:  roles in _CASHFLOW_INFLOW_ROLES with amount_cents > 0.
    Outflows: abs(amount_cents) where amount_cents < 0.
    Zero-inflow months are included, not skipped.
    All amounts integer cents. No floats.
    Returns list sorted by month ascending.
    """
    monthly_in: dict[str, int] = {}
    monthly_out: dict[str, int] = {}
    months_seen: set[str] = set()

    for txn in transactions:
        amount = txn.get("amount_cents", 0)
        if not isinstance(amount, int):
            raise ValueError(
                f"Non-integer amount_cents: {amount} on txn {txn.get('txn_id')}"
            )
        txn_date = txn.get("txn_date", "")
        if not txn_date:
            continue
        month = str(txn_date)[:7]
        if len(month) < 7:
            continue
        months_seen.add(month)

        role = txn.get("role") or txn.get("classification") or ""
        if role in _CASHFLOW_INFLOW_ROLES and amount > 0:
            monthly_in[month] = monthly_in.get(month, 0) + amount
        elif amount < 0:
            monthly_out[month] = monthly_out.get(month, 0) + abs(amount)

    result = []
    prev_net: int | None = None
    for month in sorted(months_seen):
        inflow = monthly_in.get(month, 0)
        outflow = monthly_out.get(month, 0)
        net = inflow - outflow
        if prev_net is None:
            mom_change_bps = None
            mom_reliable = False
        else:
            mom_change_bps = _mom_change_bps(prev_net, net)
            mom_reliable = abs(prev_net) >= _MOM_RELIABLE_THRESHOLD_CENTS
        result.append({
            "month": month,
            "inflow_cents": inflow,
            "outflow_cents": outflow,
            "net_cents": net,
            "mom_change_bps": mom_change_bps,
            "mom_reliable": mom_reliable,
        })
        prev_net = net
    return result
