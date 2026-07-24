"""
Parity post-extraction analytics layer.
Operates on classified RawTransaction lists.
All arithmetic in integer cents. No floats.
"""
from __future__ import annotations

from collections import defaultdict
from typing import List, Dict, Any, Optional

from app.models import RawTransaction


def _parse_amount(raw: str) -> int:
    """Parse amount string to integer cents. Returns 0 on failure."""
    if not raw or not raw.strip():
        return 0
    cleaned = raw.strip().replace(",", "").replace(" CR", "").replace(" DR", "")
    try:
        return int(round(float(cleaned) * 100))
    except ValueError:
        return 0


def _parse_balance(raw: str) -> tuple[int, bool]:
    """
    Parse balance string to (cents, is_overdraft).
    Returns (0, False) on failure.
    """
    if not raw or not raw.strip():
        return (0, False)
    is_dr = "DR" in raw.upper()
    cleaned = raw.strip().replace(",", "").replace(" CR", "").replace(" DR", "")
    try:
        cents = int(round(float(cleaned) * 100))
        return (cents, is_dr)
    except ValueError:
        return (0, False)


def _month_key(date_raw: str) -> str:
    """Extract YYYY-MM from ISO date string. Returns empty string on failure."""
    if not date_raw or len(date_raw) < 7:
        return ""
    return date_raw[:7]


def _extract_counterparty(description: Optional[str], _pattern_hint: Optional[str]) -> str:
    """Extract counterparty from description. Stub for trimmed analytics."""
    if not description or not description.strip():
        return "unknown"
    return (description.strip() or "unknown")[:80]


REVENUE_HINTS = {
    "MPESA_C2B",
    "POS_RECEIPT",
    "FUND_INFLOW",
    "INWARD_EFT_CREDIT",
}

EXPENSE_HINTS = {
    "SAFEWAYS_WITHDRAWAL",
    "NAMED_PERSON_TRANSFER",
    "CASH_WITHDRAWAL",
    "PESALINK_TRANSFER",
    "MPESA_TRANSFER",
    "AIRTIME_PURCHASE",
    "CARD_PURCHASE",
}

BANK_FEE_HINTS = {
    "BANK_CHARGE",
    "INTEREST",
    "KPLC_PREPAID",
}

NON_REVENUE_HINTS = EXPENSE_HINTS | BANK_FEE_HINTS | {"REVERSAL_PAIR"}


def revenue_quality(transactions: List[RawTransaction]) -> Dict[str, Any]:
    """
    Quality of revenue analysis.
    Strips non-revenue items and aggregates by month and counterparty.
    """
    revenue_txns = [
        t for t in transactions
        if t.pattern_hint in REVENUE_HINTS
        and t.pattern_hint != "REVERSAL_PAIR"
    ]

    monthly: Dict[str, int] = defaultdict(int)
    by_counterparty: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"total_cents": 0, "count": 0, "months": set(), "monthly_counts": defaultdict(int)}
    )

    for t in revenue_txns:
        amount = _parse_amount(t.credit_raw)
        month = _month_key(t.date_raw)
        if month:
            monthly[month] += amount

        counterparty = _extract_counterparty(t.description, t.pattern_hint)
        by_counterparty[counterparty]["total_cents"] += amount
        by_counterparty[counterparty]["count"] += 1
        if month:
            by_counterparty[counterparty]["months"].add(month)
            by_counterparty[counterparty]["monthly_counts"][month] += 1

    monthly_list = sorted(
        [{"month": k, "total_cents": v} for k, v in monthly.items()],
        key=lambda x: x["month"],
    )

    total_revenue_cents = sum(monthly.values())
    month_count = len(monthly_list)
    avg_monthly_cents = total_revenue_cents // month_count if month_count else 0

    counterparty_list = sorted(
        [
            {
                "counterparty": k,
                "total_cents": v["total_cents"],
                "pct_bps": int(v["total_cents"] * 10000 // total_revenue_cents) if total_revenue_cents else 0,
                "transaction_count": v["count"],
                "avg_transaction_cents": v["total_cents"] // v["count"] if v["count"] else 0,
                "active_months": len(v["months"]),
                "monthly_frequency": dict(sorted(v["monthly_counts"].items())),
            }
            for k, v in by_counterparty.items()
        ],
        key=lambda x: x["total_cents"],
        reverse=True,
    )

    return {
        "total_revenue_cents": total_revenue_cents,
        "average_monthly_revenue_cents": avg_monthly_cents,
        "month_count": month_count,
        "monthly_breakdown": monthly_list,
        "counterparty_breakdown": counterparty_list,
        "transaction_count": len(revenue_txns),
        "pending_classification_count": sum(
            1 for t in transactions
            if t.classification_status == "PENDING_CLASSIFICATION"
            and t.pattern_hint in REVENUE_HINTS
        ),
    }


def expense_patterns(transactions: List[RawTransaction]) -> Dict[str, Any]:
    """
    Expense pattern analysis.
    Ranks by category and counterparty. Flags owner distributions and large single transactions.
    """
    expense_txns = [
        t for t in transactions
        if t.pattern_hint in EXPENSE_HINTS
    ]

    total_expense_cents = sum(_parse_amount(t.debit_raw) for t in expense_txns)

    by_category: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"total_cents": 0, "count": 0}
    )
    by_counterparty: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"total_cents": 0, "count": 0, "category": ""}
    )
    large_transactions = []
    owner_distributions = []

    large_threshold = 5000000

    for t in expense_txns:
        amount = _parse_amount(t.debit_raw)
        category = t.pattern_hint
        by_category[category]["total_cents"] += amount
        by_category[category]["count"] += 1

        counterparty = _extract_counterparty(t.description, t.pattern_hint)
        by_counterparty[counterparty]["total_cents"] += amount
        by_counterparty[counterparty]["count"] += 1
        by_counterparty[counterparty]["category"] = category

        if amount >= large_threshold:
            large_transactions.append({
                "date": t.date_raw,
                "description": t.description[:80],
                "amount_cents": amount,
                "category": category,
            })

        if t.pattern_hint in {"NAMED_PERSON_TRANSFER", "CASH_WITHDRAWAL"}:
            owner_distributions.append({
                "date": t.date_raw,
                "description": t.description[:80],
                "amount_cents": amount,
            })

    category_list = sorted(
        [
            {
                "category": k,
                "total_cents": v["total_cents"],
                "count": v["count"],
                "pct_bps": int(v["total_cents"] * 10000 // total_expense_cents)
                if total_expense_cents else 0,
            }
            for k, v in by_category.items()
        ],
        key=lambda x: x["total_cents"],
        reverse=True,
    )

    counterparty_list = sorted(
        [
            {
                "counterparty": k,
                "total_cents": v["total_cents"],
                "count": v["count"],
                "pct_bps": int(v["total_cents"] * 10000 // total_expense_cents)
                if total_expense_cents else 0,
                "category": v["category"],
            }
            for k, v in by_counterparty.items()
        ],
        key=lambda x: x["total_cents"],
        reverse=True,
    )

    return {
        "total_expense_cents": total_expense_cents,
        "category_breakdown": category_list,
        "counterparty_breakdown": counterparty_list[:10],
        "large_transactions": sorted(
            large_transactions, key=lambda x: x["amount_cents"], reverse=True
        ),
        "owner_distributions": owner_distributions,
        "transaction_count": len(expense_txns),
    }


def cash_position(transactions: List[RawTransaction], threshold_cents: int = 50000000) -> Dict[str, Any]:
    """
    Cash position analysis.
    Tracks running balance, flags overdraft events and balance below threshold.
    threshold_cents defaults to KES 500,000 (50000000 cents).
    """
    sorted_txns = sorted(
        [t for t in transactions if t.balance_raw and t.date_raw],
        key=lambda x: (x.date_raw, x.row_index),
    )

    overdraft_events = []
    below_threshold_events = []
    balance_history = []

    for t in sorted_txns:
        balance_cents, is_dr = _parse_balance(t.balance_raw)
        signed_balance = -balance_cents if is_dr else balance_cents

        balance_history.append({
            "date": t.date_raw,
            "balance_cents": signed_balance,
            "is_overdraft": is_dr,
        })

        if is_dr:
            overdraft_events.append({
                "date": t.date_raw,
                "balance_cents": signed_balance,
                "description": t.description[:60],
            })

        if signed_balance < threshold_cents and not is_dr:
            below_threshold_events.append({
                "date": t.date_raw,
                "balance_cents": signed_balance,
                "description": t.description[:60],
            })

    min_balance = min((b["balance_cents"] for b in balance_history), default=0)
    max_balance = max((b["balance_cents"] for b in balance_history), default=0)

    return {
        "overdraft_count": len(overdraft_events),
        "overdraft_events": overdraft_events[:10],
        "below_threshold_count": len(below_threshold_events),
        "below_threshold_events": below_threshold_events[:10],
        "threshold_cents": threshold_cents,
        "min_balance_cents": min_balance,
        "max_balance_cents": max_balance,
        "balance_history_count": len(balance_history),
    }


def credit_scoring_inputs(transactions: List[RawTransaction]) -> Dict[str, Any]:
    """
    Sayuni Capital Section 01 — Credit Scoring Inputs.
    Computes structured scoring metrics for credit committee use.
    All arithmetic in integer cents. No floats.
    """
    # Monthly inflows — revenue only, excluding loans/reversals/fees
    monthly_in: Dict[str, int] = defaultdict(int)
    monthly_out: Dict[str, int] = defaultdict(int)
    loan_repayment_total = 0
    total_outflow = 0
    payroll_months: set = set()
    tax_months: set = set()
    tax_total = 0

    for t in transactions:
        month = _month_key(t.date_raw)
        if not month:
            continue
        hint = t.pattern_hint or ""
        credit = _parse_amount(t.credit_raw)
        debit = _parse_amount(t.debit_raw)

        # Revenue inflows only — exclude loans, reversals, fees
        if hint in REVENUE_HINTS and credit > 0:
            monthly_in[month] += credit

        # All outflows for total_outflow
        if debit > 0:
            total_outflow += debit
            monthly_out[month] += debit

        # Loan repayment burden
        if hint in {"PESALINK_TRANSFER"} or (t.description and any(
            kw in t.description.upper() for kw in ["LOAN REPAY", "LOAN REPAYMENT", "FULIZA", "TALA", "KCB LOOP"]
        )):
            loan_repayment_total += debit

        # Payroll detection
        if t.description and any(
            kw in t.description.upper() for kw in ["SALARY", "PAYROLL", "WAGES", "NET PAY"]
        ):
            if month:
                payroll_months.add(month)

        # KRA / tax detection — debit-only (payments TO KRA, not refunds/reversals)
        if debit > 0 and t.description and any(
            kw in t.description.upper() for kw in ["KRA", "PAYE", "VAT", "TAX"]
        ):
            tax_months.add(month)
            tax_total += debit

    # Monthly inflow stats
    all_months = sorted(monthly_in.keys())
    month_count = len(all_months)
    inflow_values = [monthly_in[m] for m in all_months]

    avg_monthly_inflow = sum(inflow_values) // month_count if month_count else 0

    # Median — integer arithmetic
    if inflow_values:
        sorted_vals = sorted(inflow_values)
        n = len(sorted_vals)
        if n % 2 == 1:
            median_monthly_inflow = sorted_vals[n // 2]
        else:
            median_monthly_inflow = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) // 2
    else:
        median_monthly_inflow = 0

    # Monthly outflow stats
    out_months = sorted(monthly_out.keys())
    out_values = [monthly_out[m] for m in out_months]
    avg_monthly_outflow = sum(out_values) // len(out_values) if out_values else 0

    # Net positions per month — use union of all months
    all_period_months = sorted(set(list(monthly_in.keys()) + list(monthly_out.keys())))
    net_positions = {m: monthly_in.get(m, 0) - monthly_out.get(m, 0) for m in all_period_months}
    net_values = list(net_positions.values())

    avg_net = sum(net_values) // len(net_values) if net_values else 0
    peak_net = max(net_values) if net_values else 0
    trough_net = min(net_values) if net_values else 0

    # Revenue growth — first vs last month with inflow data
    revenue_growth_bps = 0
    if len(inflow_values) >= 2 and inflow_values[0] > 0:
        revenue_growth_bps = ((inflow_values[-1] - inflow_values[0]) * 10000) // inflow_values[0]

    # Loan repayment burden — % of total outflow in basis points
    loan_repayment_burden_bps = 0
    if total_outflow > 0 and loan_repayment_total > 0:
        loan_repayment_burden_bps = (loan_repayment_total * 10000) // total_outflow

    # Payroll stability
    statement_months = len(all_period_months)
    payroll_month_count = len(payroll_months)
    if statement_months == 0:
        payroll_stability = "NOT_DETECTED"
    elif payroll_month_count == 0:
        payroll_stability = "NOT_DETECTED"
    elif payroll_month_count == statement_months:
        payroll_stability = "CONSISTENT"
    elif payroll_month_count >= statement_months * 8 // 10:
        payroll_stability = "MOSTLY_CONSISTENT"
    else:
        payroll_stability = "IRREGULAR"

    # KRA compliance
    if tax_months:
        # Check for gaps — any interior month missing tax payment
        all_months_set = set(all_period_months)
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


# Role-to-category mapping for monthly entity breakdown
_CATEGORY_MAP = {
    # Revenue
    "revenue_operational": "revenue_in",
    "mpesa_inflow": "revenue_in",
    "pesalink_inflow": "revenue_in",
    # Suppliers
    "supplier": "suppliers",
    "bill_payment": "suppliers",
    "merchant_payment": "suppliers",
    "mobile_money_transfer": "suppliers",
    "cash_withdrawal": "suppliers",
    "airtime_purchase": "suppliers",
    "named_counterparty_debit": "suppliers",
    "person_to_person_transfer": "suppliers",
    # Payroll
    "payroll": "payroll",
    # Loan repayment
    "loan_repayment": "loan_repayment",
    # Tax
    "tax_payment": "tax",
    # Excluded from breakdown — not an operational category
    "bank_charge": None,
    "loan_inflow": None,
    "capital_injection": None,
    "reversal_credit": None,
    "reversal_debit": None,
    "needs_review": None,
    "opening_balance": None,
    "closing_balance": None,
    "transfer": None,
    "other": None,
    "revenue_non_operational": None,
    "currency_conversion": None,  # excluded from all operational categories
}


# NOTE: a raw, pre-classification monthly_cashflow() used to live here, feeding
# pds_documents.analytics.monthly_cashflow. It summed credit/debit statement
# columns directly with no role classification (classification happens later,
# in the backend pipeline) — a second, independent, and silently divergent
# definition of "monthly cashflow" from the trusted, role-classified one in
# backend/v1/analytics.py::monthly_cashflow(), which the app's Analysis tab and
# (as of the same fix that removed this) the exported PDF both use, sourced
# from the deal's sealed canonical_json. Removed rather than left unused, so it
# can't be silently reconnected later and reintroduce the same class of bug —
# see backend/v1/analysis/snapshot_html_renderer.py's "Monthly cashflow"
# comment for the full history.


def entity_discovery_flags(transactions: List[RawTransaction]) -> List[Dict[str, Any]]:
    """
    Surface findings not typically declared in loan applications.
    Mirrors Sayuni Capital Section 05 format.
    """
    flags = []

    fund_inflows = [t for t in transactions if t.pattern_hint == "FUND_INFLOW"]
    for t in fund_inflows:
        amount = _parse_amount(t.credit_raw)
        counterparty = _extract_counterparty(t.description, t.pattern_hint)
        flags.append({
            "finding": f"{counterparty} — undeclared fund inflow",
            "category": "UNDISCLOSED_LOAN_OR_INVESTMENT",
            "value_cents": amount,
            "date": t.date_raw,
            "action": "CONFIRM WITH APPLICANT",
        })

    named_person = [t for t in transactions if t.pattern_hint == "NAMED_PERSON_TRANSFER"]
    for t in named_person:
        amount = _parse_amount(t.debit_raw)
        flags.append({
            "finding": f"{t.description[:60]} — large named person transfer",
            "category": "POSSIBLE_OWNER_DISTRIBUTION",
            "value_cents": amount,
            "date": t.date_raw,
            "action": "VERIFY RELATIONSHIP TO BUSINESS",
        })

    pesalink = [t for t in transactions if t.pattern_hint == "PESALINK_TRANSFER"]
    for t in pesalink:
        amount = _parse_amount(t.debit_raw)
        flags.append({
            "finding": "PesaLink transfer — possible intercompany obligation",
            "category": "POSSIBLE_INTERCOMPANY_TRANSFER",
            "value_cents": amount,
            "date": t.date_raw,
            "action": "CONFIRM BENEFICIARY AND PURPOSE",
        })

    reversals = [t for t in transactions if t.pattern_hint == "REVERSAL_PAIR"]
    if reversals:
        flags.append({
            "finding": f"{len(reversals)} reversed transactions detected",
            "category": "REVERSAL_PATTERN",
            "value_cents": sum(_parse_amount(t.debit_raw) for t in reversals),
            "date": reversals[0].date_raw,
            "action": "REVIEW FOR FAILED PAYMENTS OR DISPUTES",
        })

    pending = [t for t in transactions if t.classification_status == "PENDING_CLASSIFICATION"
               and t.pattern_hint not in {"POS_RECEIPT", "REVERSAL_PAIR"}]
    if pending:
        flags.append({
            "finding": f"{len(pending)} transactions require analyst classification",
            "category": "PENDING_CLASSIFICATION",
            "value_cents": 0,
            "date": "",
            "action": "CLASSIFY BEFORE FINALISING REPORT",
        })

    return flags


def monthly_entity_breakdown(transactions: List[RawTransaction]) -> List[Dict[str, Any]]:
    """
    Sayuni Capital Section 03 — Monthly Entity Breakdown by Category.
    Five columns per month: Revenue In, Suppliers, Payroll, Loan Repayment, Tax.
    All arithmetic in integer cents. No floats.
    """
    # Accumulate by month and category
    monthly: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            "revenue_in": 0,
            "suppliers": 0,
            "payroll": 0,
            "loan_repayment": 0,
            "tax": 0,
        }
    )

    for t in transactions:
        month = _month_key(t.date_raw)
        if not month:
            continue

        hint = (t.pattern_hint or "").upper()
        desc = (t.description or "").upper()
        credit = _parse_amount(t.credit_raw)
        debit = _parse_amount(t.debit_raw)

        # Determine role from pattern_hint first, fall back to description keywords
        # This works for extractors that set pattern_hint (Co-op)
        # and for those that don't yet (KCB, ABSA etc will rely on description)
        role = None

        if hint == "MPESA_C2B":
            role = "revenue_operational"
        elif hint == "POS_RECEIPT":
            role = "revenue_operational"
        elif hint == "FUND_INFLOW":
            role = None  # excluded
        elif hint == "SAFEWAYS_WITHDRAWAL":
            role = "supplier"
        elif hint == "BANK_CHARGE":
            role = "bank_charge"
        elif hint == "KPLC_PREPAID":
            role = "bill_payment"
        elif hint == "NAMED_PERSON_TRANSFER":
            role = "named_counterparty_debit"
        elif hint == "PESALINK_TRANSFER":
            role = "loan_repayment"
        elif hint == "REVERSAL_PAIR":
            role = "reversal_credit"
        elif hint == "CASH_WITHDRAWAL":
            role = "cash_withdrawal"
        elif hint == "AIRTIME_PURCHASE":
            role = "airtime_purchase"
        elif hint == "MPESA_TRANSFER":
            role = "mobile_money_transfer"
        elif hint == "INTEREST":
            role = "bank_charge"

        # If no pattern_hint match, use description keywords
        if role is None and hint == "":
            if any(kw in desc for kw in ["SALARY", "PAYROLL", "WAGES", "NET PAY"]):
                role = "payroll"
            elif any(kw in desc for kw in ["KRA", "PAYE", "VAT", "TAX"]):
                role = "tax_payment"
            elif any(kw in desc for kw in ["LOAN REPAY", "FULIZA", "TALA"]):
                role = "loan_repayment"

        if role is None:
            continue

        category = _CATEGORY_MAP.get(role)
        if category is None:
            continue

        # Revenue categories use credit amounts
        if category == "revenue_in" and credit > 0:
            monthly[month][category] += credit
        # Expense categories use debit amounts
        elif category in ("suppliers", "payroll", "loan_repayment", "tax") and debit > 0:
            monthly[month][category] += debit

    # Sort by month and return
    result = []
    for month in sorted(monthly.keys()):
        row = monthly[month]
        result.append({
            "month": month,
            "revenue_in_cents": row["revenue_in"],
            "suppliers_cents": row["suppliers"],
            "payroll_cents": row["payroll"],
            "loan_repayment_cents": row["loan_repayment"],
            "tax_cents": row["tax"],
        })

    return result


_FX_DESC_KEYWORDS = ("CONVERSION TRANSFER", "FX CONVERSION", "CURRENCY CONVERSION", "CONVERSION")
_FX_CURRENCY_CODES = ("EUR", "USD", "GBP", "CHF", "JPY", "CNY", "AED", "ZAR")


def _is_fx_conversion(description: Optional[str]) -> bool:
    """Detect foreign currency conversion transactions from description."""
    if not description:
        return False
    d = description.upper()
    has_kw = any(kw in d for kw in _FX_DESC_KEYWORDS)
    has_cc = any(cc in d for cc in _FX_CURRENCY_CODES)
    if has_kw and has_cc:
        return True
    if has_cc and ("TO KSH" in d or "TO KES" in d):
        return True
    import re
    if has_cc and re.search(r'AT\s+\d+\.?\d*', d) and ("TRF FROM" in d or "TRANSFER FROM" in d):
        return True
    return False


def fx_conversion_metrics(transactions: List[RawTransaction]) -> Dict[str, Any]:
    """Compute FX conversion metrics. Mirrors classifier currency_conversion role detection."""
    fx_txns = [t for t in transactions if _is_fx_conversion(t.description)]

    if not fx_txns:
        return {
            "total_fx_conversion_cents": 0,
            "fx_conversion_count": 0,
            "fx_conversion_months": [],
            "largest_fx_conversion_cents": 0,
            "fx_as_pct_of_inflow": 0,
        }

    total_fx = sum(_parse_amount(t.credit_raw) for t in fx_txns)
    months = sorted({_month_key(t.date_raw) for t in fx_txns if _month_key(t.date_raw)})
    largest = max((_parse_amount(t.credit_raw) for t in fx_txns), default=0)

    total_credits = sum(_parse_amount(t.credit_raw) for t in transactions)
    fx_pct_bps = int(total_fx * 10000 // total_credits) if total_credits > 0 else 0

    return {
        "total_fx_conversion_cents": total_fx,
        "fx_conversion_count": len(fx_txns),
        "fx_conversion_months": months,
        "largest_fx_conversion_cents": largest,
        "fx_as_pct_of_inflow_bps": fx_pct_bps,
    }


def run_analytics(transactions: List[RawTransaction], threshold_cents: int = 50000000) -> Dict[str, Any]:
    """
    Run all analytics modules and return combined result.
    """
    return {
        "summary": {
            "total_transactions": len(transactions),
            "auto_classified": sum(1 for t in transactions if t.classification_status == "AUTO_CLASSIFIED"),
            "pending_classification": sum(1 for t in transactions if t.classification_status == "PENDING_CLASSIFICATION"),
            "analyst_classified": sum(1 for t in transactions if t.classification_status == "ANALYST_CLASSIFIED"),
        },
        "credit_scoring_inputs": credit_scoring_inputs(transactions),
        "monthly_entity_breakdown": monthly_entity_breakdown(transactions),
        "revenue_quality": revenue_quality(transactions),
        "expense_patterns": expense_patterns(transactions),
        "cash_position": cash_position(transactions, threshold_cents),
        "entity_discovery_flags": entity_discovery_flags(transactions),
        "fx_conversion_metrics": fx_conversion_metrics(transactions),
    }
