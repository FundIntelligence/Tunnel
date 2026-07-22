"""
Tests for Parity analytics module.
All amounts in integer cents. No floats allowed.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics import (
    annual_revenue_summary,
    loan_drawdowns,
    kra_summary,
    top_expenses_with_frequency,
    monthly_cashflow,
    credit_scoring_inputs,
)


# ── annual_revenue_summary ─────────────────────────────────────────────────────

def test_annual_revenue_excludes_loan_inflow():
    txns = [
        {"role": "revenue_operational", "amount_cents": 1_000_000_00, "txn_date": "2024-03-15"},
        {"role": "loan_inflow", "amount_cents": 500_000_00, "txn_date": "2024-03-20"},
    ]
    result = annual_revenue_summary(txns)
    assert result["annual_revenue_cents"][2024] == 1_000_000_00


def test_annual_revenue_multi_year():
    txns = [
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2024-01-01"},
        {"role": "revenue_operational", "amount_cents": 200_000_00, "txn_date": "2025-01-01"},
        {"role": "mpesa_inflow", "amount_cents": 50_000_00, "txn_date": "2025-06-15"},
    ]
    result = annual_revenue_summary(txns)
    assert result["annual_revenue_cents"][2024] == 100_000_00
    assert result["annual_revenue_cents"][2025] == 250_000_00
    assert result["total_all_years_cents"] == 350_000_00


def test_annual_revenue_rejects_floats():
    txns = [{"role": "revenue_operational", "amount_cents": 100.5, "txn_date": "2024-01-01"}]
    with pytest.raises(ValueError):
        annual_revenue_summary(txns)


def test_annual_revenue_excludes_negative():
    txns = [
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2024-01-01"},
        {"role": "revenue_operational", "amount_cents": -50_000_00, "txn_date": "2024-01-02"},
    ]
    result = annual_revenue_summary(txns)
    assert result["annual_revenue_cents"][2024] == 100_000_00


# ── loan_drawdowns ─────────────────────────────────────────────────────────────

def test_loan_drawdowns_basic():
    txns = [
        {"role": "loan_inflow", "amount_cents": 1_136_068_00, "txn_date": "2024-03-15", "entity_name": "Equity OD"},
        {"role": "revenue_operational", "amount_cents": 500_000_00, "txn_date": "2024-03-16", "entity_name": "Customer"},
    ]
    result = loan_drawdowns(txns)
    assert result["drawdown_count"] == 1
    assert result["total_drawdown_cents"] == 1_136_068_00


def test_loan_drawdowns_excludes_revenue():
    txns = [
        {"role": "loan_inflow", "amount_cents": 100_000_00, "txn_date": "2024-01-01"},
        {"role": "loan_inflow", "amount_cents": 200_000_00, "txn_date": "2024-02-01"},
        {"role": "revenue_operational", "amount_cents": 999_000_00, "txn_date": "2024-01-15"},
    ]
    result = loan_drawdowns(txns)
    assert result["drawdown_count"] == 2
    assert result["total_drawdown_cents"] == 300_000_00


def test_loan_drawdowns_sorted_descending():
    txns = [
        {"role": "loan_inflow", "amount_cents": 100_00, "txn_date": "2024-01-01"},
        {"role": "loan_inflow", "amount_cents": 200_00, "txn_date": "2024-03-01"},
        {"role": "loan_inflow", "amount_cents": 150_00, "txn_date": "2024-02-01"},
    ]
    result = loan_drawdowns(txns)
    dates = [d["txn_date"] for d in result["drawdowns"]]
    assert dates == ["2024-03-01", "2024-02-01", "2024-01-01"]


# ── kra_summary ────────────────────────────────────────────────────────────────

def test_kra_summary_compliant():
    txns = [
        {"role": "tax_payment", "amount_cents": -50_000_00, "txn_date": f"2024-{str(m).zfill(2)}-15"}
        for m in range(1, 12)
    ]
    result = kra_summary(txns)
    assert result["compliance"] == "COMPLIANT"
    assert result["months_with_payment"] == 11
    assert result["total_tax_cents"] == 50_000_00 * 11


def test_kra_summary_not_detected():
    txns = [{"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2024-01-01"}]
    result = kra_summary(txns)
    assert result["compliance"] == "NOT_DETECTED"
    assert result["total_tax_cents"] == 0


def test_kra_summary_partial():
    txns = [
        {"role": "tax_payment", "amount_cents": -30_000_00, "txn_date": "2024-01-15"},
        {"role": "tax_payment", "amount_cents": -30_000_00, "txn_date": "2024-03-15"},
    ]
    result = kra_summary(txns)
    assert result["compliance"] == "PARTIAL"
    assert result["months_with_payment"] == 2


# ── top_expenses_with_frequency ────────────────────────────────────────────────

def test_top_expenses_with_frequency():
    txns = [
        {"role": "supplier", "amount_cents": -100_000_00, "entity_name": "Supplier A", "txn_date": "2024-01-01"},
        {"role": "supplier", "amount_cents": -100_000_00, "entity_name": "Supplier A", "txn_date": "2024-01-15"},
        {"role": "supplier", "amount_cents": -500_000_00, "entity_name": "Supplier B", "txn_date": "2024-01-10"},
    ]
    result = top_expenses_with_frequency(txns, top_n=10)
    assert result[0]["entity_name"] == "Supplier B"
    assert result[0]["txn_count"] == 1
    assert result[1]["entity_name"] == "Supplier A"
    assert result[1]["txn_count"] == 2
    assert result[1]["avg_transaction_cents"] == 100_000_00


def test_top_expenses_excludes_revenue():
    txns = [
        {"role": "revenue_operational", "amount_cents": 999_000_00, "entity_name": "Big Customer"},
        {"role": "supplier", "amount_cents": -100_000_00, "entity_name": "Supplier A"},
    ]
    result = top_expenses_with_frequency(txns)
    assert len(result) == 1
    assert result[0]["entity_name"] == "Supplier A"


# ── monthly_cashflow ───────────────────────────────────────────────────────────

def test_monthly_cashflow_basic():
    txns = [
        {"role": "revenue_operational", "amount_cents": 2_740_000_00, "txn_date": "2025-01-10"},
        {"role": "supplier", "amount_cents": -2_680_000_00, "txn_date": "2025-01-20"},
        {"role": "revenue_operational", "amount_cents": 3_120_000_00, "txn_date": "2025-02-05"},
        {"role": "payroll", "amount_cents": -2_910_000_00, "txn_date": "2025-02-28"},
    ]
    result = monthly_cashflow(txns)
    assert len(result) == 2
    jan = result[0]
    assert jan["month"] == "2025-01"
    assert jan["inflow_cents"] == 2_740_000_00
    assert jan["outflow_cents"] == 2_680_000_00
    assert jan["net_cents"] == 60_000_00
    feb = result[1]
    assert feb["month"] == "2025-02"
    assert feb["net_cents"] == 210_000_00


def test_monthly_cashflow_negative_net():
    txns = [
        {"role": "mpesa_inflow", "amount_cents": 2_280_000_00, "txn_date": "2025-03-15"},
        {"role": "supplier", "amount_cents": -2_540_000_00, "txn_date": "2025-03-20"},
    ]
    result = monthly_cashflow(txns)
    assert len(result) == 1
    assert result[0]["net_cents"] == -260_000_00


def test_monthly_cashflow_inflow_roles_only():
    # loan_inflow and capital_injection count as inflows; transfer does not
    txns = [
        {"role": "loan_inflow", "amount_cents": 1_000_000_00, "txn_date": "2025-04-01"},
        {"role": "capital_injection", "amount_cents": 500_000_00, "txn_date": "2025-04-05"},
        {"role": "transfer", "amount_cents": 200_000_00, "txn_date": "2025-04-10"},
        {"role": "supplier", "amount_cents": -300_000_00, "txn_date": "2025-04-15"},
    ]
    result = monthly_cashflow(txns)
    assert len(result) == 1
    assert result[0]["inflow_cents"] == 1_500_000_00
    assert result[0]["outflow_cents"] == 300_000_00


def test_monthly_cashflow_zero_inflow_month_included():
    # A month with only outflows still appears as a row
    txns = [
        {"role": "revenue_operational", "amount_cents": 1_000_000_00, "txn_date": "2025-01-10"},
        {"role": "supplier", "amount_cents": -500_000_00, "txn_date": "2025-02-10"},
    ]
    result = monthly_cashflow(txns)
    assert len(result) == 2
    feb = result[1]
    assert feb["month"] == "2025-02"
    assert feb["inflow_cents"] == 0
    assert feb["outflow_cents"] == 500_000_00
    assert feb["net_cents"] == -500_000_00


def test_monthly_cashflow_sorted_ascending():
    txns = [
        {"role": "mpesa_inflow", "amount_cents": 100_00, "txn_date": "2025-03-01"},
        {"role": "mpesa_inflow", "amount_cents": 100_00, "txn_date": "2025-01-01"},
        {"role": "mpesa_inflow", "amount_cents": 100_00, "txn_date": "2025-02-01"},
    ]
    result = monthly_cashflow(txns)
    months = [r["month"] for r in result]
    assert months == ["2025-01", "2025-02", "2025-03"]


def test_monthly_cashflow_rejects_float_amount():
    txns = [{"role": "revenue_operational", "amount_cents": 100.5, "txn_date": "2025-01-01"}]
    with pytest.raises(ValueError):
        monthly_cashflow(txns)


def test_monthly_cashflow_empty():
    assert monthly_cashflow([]) == []


def test_monthly_cashflow_skips_missing_date():
    txns = [
        {"role": "revenue_operational", "amount_cents": 1_000_00, "txn_date": ""},
        {"role": "revenue_operational", "amount_cents": 2_000_00, "txn_date": "2025-01-01"},
    ]
    result = monthly_cashflow(txns)
    assert len(result) == 1
    assert result[0]["inflow_cents"] == 2_000_00


def test_monthly_cashflow_all_integer_types():
    txns = [
        {"role": "pesalink_inflow", "amount_cents": 5_000_00, "txn_date": "2025-05-10"},
        {"role": "bank_charge", "amount_cents": -50_00, "txn_date": "2025-05-15"},
    ]
    result = monthly_cashflow(txns)
    assert all(isinstance(r["inflow_cents"], int) for r in result)
    assert all(isinstance(r["outflow_cents"], int) for r in result)
    assert all(isinstance(r["net_cents"], int) for r in result)


# ── credit_scoring_inputs ──────────────────────────────────────────────────────

def test_credit_scoring_inputs_uses_role_not_keywords():
    """Loan repayment burden must come from the real classifier's `loan_repayment`
    role, not a keyword/pattern-hint match — a Pesalink supplier payment must
    NOT be counted as loan repayment just because it moved via Pesalink."""
    txns = [
        {"role": "revenue_operational", "amount_cents": 1_000_000_00, "txn_date": "2025-01-05"},
        {"role": "pesalink_outflow", "amount_cents": -400_000_00, "txn_date": "2025-01-10"},  # supplier via pesalink, NOT a loan
        {"role": "loan_repayment", "amount_cents": -100_000_00, "txn_date": "2025-01-15"},
    ]
    result = credit_scoring_inputs(txns)
    # total_outflow = 500_000_00; loan_repayment_total = 100_000_00 -> 2000 bps (20%)
    assert result["loan_repayment_burden_bps"] == 2000


def test_credit_scoring_inputs_median_and_average_inflow():
    txns = [
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2025-01-05"},
        {"role": "mpesa_inflow", "amount_cents": 200_000_00, "txn_date": "2025-02-05"},
        {"role": "revenue_operational", "amount_cents": 300_000_00, "txn_date": "2025-03-05"},
    ]
    result = credit_scoring_inputs(txns)
    assert result["average_monthly_inflow_cents"] == 200_000_00
    assert result["median_monthly_inflow_cents"] == 200_000_00
    assert result["month_count_with_inflow"] == 3


def test_credit_scoring_inputs_excludes_loan_inflow_and_capital_injection():
    txns = [
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2025-01-05"},
        {"role": "loan_inflow", "amount_cents": 5_000_000_00, "txn_date": "2025-01-06"},
        {"role": "capital_injection", "amount_cents": 2_000_000_00, "txn_date": "2025-01-07"},
    ]
    result = credit_scoring_inputs(txns)
    assert result["average_monthly_inflow_cents"] == 100_000_00


def test_credit_scoring_inputs_peak_and_trough_net_position():
    txns = [
        {"role": "revenue_operational", "amount_cents": 500_000_00, "txn_date": "2025-01-05"},
        {"role": "bank_charge", "amount_cents": -100_000_00, "txn_date": "2025-01-06"},
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2025-02-05"},
        {"role": "bank_charge", "amount_cents": -300_000_00, "txn_date": "2025-02-06"},
    ]
    result = credit_scoring_inputs(txns)
    assert result["peak_net_position_cents"] == 400_000_00
    assert result["trough_net_position_cents"] == -200_000_00


def test_credit_scoring_inputs_payroll_and_kra_use_roles():
    txns = [
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2025-01-05"},
        {"role": "payroll", "amount_cents": -50_000_00, "txn_date": "2025-01-10"},
        {"role": "tax_payment", "amount_cents": -10_000_00, "txn_date": "2025-01-20"},
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2025-02-05"},
        {"role": "payroll", "amount_cents": -50_000_00, "txn_date": "2025-02-10"},
        {"role": "tax_payment", "amount_cents": -10_000_00, "txn_date": "2025-02-20"},
    ]
    result = credit_scoring_inputs(txns)
    assert result["payroll_stability"] == "CONSISTENT"
    assert result["payroll_months_detected"] == 2
    assert result["kra_compliance"] == "PASS"


def test_credit_scoring_inputs_kra_gaps_detected():
    txns = [
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2025-01-05"},
        {"role": "tax_payment", "amount_cents": -10_000_00, "txn_date": "2025-01-20"},
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2025-02-05"},
        # no tax_payment in Feb
    ]
    result = credit_scoring_inputs(txns)
    assert result["kra_compliance"] == "GAPS_DETECTED"


def test_credit_scoring_inputs_no_tax_transactions():
    txns = [{"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2025-01-05"}]
    result = credit_scoring_inputs(txns)
    assert result["kra_compliance"] == "NOT_DETECTED"


def test_credit_scoring_inputs_rejects_float_amount():
    txns = [{"role": "revenue_operational", "amount_cents": 100.5, "txn_date": "2025-01-01"}]
    with pytest.raises(ValueError):
        credit_scoring_inputs(txns)


def test_credit_scoring_inputs_empty():
    result = credit_scoring_inputs([])
    assert result["average_monthly_inflow_cents"] == 0
    assert result["loan_repayment_burden_bps"] == 0
    assert result["kra_compliance"] == "NOT_DETECTED"
    assert result["payroll_stability"] == "NOT_DETECTED"
