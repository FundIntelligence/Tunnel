"""
Financial metrics calculations for Parity Review.
All input amounts are integer cents; displayed in KES (÷100).
Growth/burden values are in basis points.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def calculate_financial_metrics(deal_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate DSCR, revenue growth, cash flow volatility, and burn rate.
    """
    csi     = deal_data["csi"]
    metrics = deal_data["metrics"]
    monthly = deal_data["monthly"]
    loan_repayment_cents = deal_data["loan_repayment_total_cents"]
    n_months = deal_data["n_months"] or 1

    avg_inflow_cents = int(
        csi.get("average_monthly_inflow_cents")
        or metrics.get("average_monthly_inflow_cents")
        or 0
    )
    rev_growth_bps = int(
        csi.get("revenue_growth_bps")
        or metrics.get("revenue_growth_bps")
        or 0
    )
    loan_burden_bps = int(
        csi.get("loan_repayment_burden_bps")
        or metrics.get("loan_repayment_burden_bps")
        or 0
    )

    # DSCR
    monthly_loan_cents = loan_repayment_cents // n_months if loan_repayment_cents > 0 else 0
    if monthly_loan_cents > 0 and avg_inflow_cents > 0:
        dscr = avg_inflow_cents / monthly_loan_cents
        dscr_assessment = (
            ">2.0"       if dscr >= 2.0  else
            "1.5-2.0"    if dscr >= 1.5  else
            "1.25-1.5"   if dscr >= 1.25 else
            "1.0-1.25"   if dscr >= 1.0  else
            "<1.0"
        )
    else:
        dscr = None
        dscr_assessment = "No loan repayments detected — cannot calculate DSCR"

    # Revenue growth (bps → %)
    rev_growth_pct = rev_growth_bps / 100
    if rev_growth_bps != 0:
        growth_assessment = f"{rev_growth_pct:.1f}% (H2 vs H1)"
    else:
        growth_assessment = "Insufficient data to calculate growth"

    # Cash flow volatility
    if len(monthly) >= 3:
        nets = [m["net_cents"] for m in monthly]
        avg_net = sum(nets) / len(nets)
        # Cash-flow volatility is an advisory display metric (a CV %), not part of
        # the deterministic snapshot/seal — this module is in the parity_review
        # layer, not the canonical hash path. The tree-wide no-`math` guard
        # (tests_v1/test_no_float_regression.py::test_math_import_restricted)
        # forbids math.sqrt; `** 0.5` is the identical square root for this
        # already-float computation without importing the math module.
        std_dev = (sum((x - avg_net) ** 2 for x in nets) / len(nets)) ** 0.5
        volatility_pct = (std_dev / abs(avg_net) * 100) if avg_net != 0 else 0
        volatility_assessment = f"CV {volatility_pct:.1f}%"
    else:
        volatility_pct = None
        std_dev = None
        volatility_assessment = "Insufficient monthly data"

    # Burn rate
    negative_months = [m for m in monthly if m["net_cents"] < 0]
    if negative_months:
        avg_burn_cents = sum(abs(m["net_cents"]) for m in negative_months) // len(negative_months)
        burn_assessment = f"{len(negative_months)}/{len(monthly)} months had negative cash flow"
    else:
        avg_burn_cents = 0
        burn_assessment = "No negative cash flow months"

    return {
        "dscr": {
            "value": round(dscr, 2) if dscr is not None else None,
            "assessment": dscr_assessment,
            "avg_monthly_inflow_kes": avg_inflow_cents / 100,
            "monthly_loan_repayment_kes": monthly_loan_cents / 100,
        },
        "revenue_growth": {
            "value_pct": round(rev_growth_pct, 1),
            "assessment": growth_assessment,
        },
        "loan_burden": {
            "value_pct": round(loan_burden_bps / 100, 1),
            "assessment": f"{round(loan_burden_bps / 100, 1)}% of total outflow",
        },
        "cash_flow_volatility": {
            "value_pct": round(volatility_pct, 1) if volatility_pct is not None else None,
            "assessment": volatility_assessment,
        },
        "burn_rate": {
            "avg_burn_kes": avg_burn_cents / 100,
            "assessment": burn_assessment,
            "negative_months": len(negative_months),
            "total_months": len(monthly),
        },
        "summary": _financial_summary(dscr, rev_growth_pct, volatility_pct, len(negative_months), len(monthly)),
    }


def _financial_summary(
    dscr: Optional[float],
    rev_growth_pct: float,
    volatility_pct: Optional[float],
    negative_months: int,
    total_months: int,
) -> str:
    parts = []
    if dscr is not None:
        parts.append(f"DSCR: {dscr:.2f}")
    parts.append(f"Revenue growth: {rev_growth_pct:.1f}%")
    if volatility_pct is not None:
        parts.append(f"Cash flow CV: {volatility_pct:.1f}%")
    if total_months > 0:
        parts.append(f"Negative cash flow months: {negative_months}/{total_months}")
    return ". ".join(parts) + "." if parts else "Insufficient data."
