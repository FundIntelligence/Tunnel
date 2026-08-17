"""
Tests for Parity Review declaration vs detection reconciliation.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reconciliation_credit import reconcile_declarations


def test_reconciliation_ok_within_5_percent():
    result = reconcile_declarations(
        declared_annual_revenue_cents=100_000_000_00,
        detected_annual_revenue_cents=103_000_000_00,
        declared_loans=None,
        detected_loan_drawdowns=[],
        declared_kra_compliant=None,
        detected_kra_compliance="COMPLIANT",
    )
    assert result["revenue_reconciliation"]["status"] == "OK"
    assert result["revenue_reconciliation"]["variance_bps"] == 300


def test_reconciliation_material_variance():
    result = reconcile_declarations(
        declared_annual_revenue_cents=100_000_000_00,
        detected_annual_revenue_cents=75_000_000_00,
        declared_loans=None,
        detected_loan_drawdowns=[],
        declared_kra_compliant=None,
        detected_kra_compliance="NOT_DETECTED",
    )
    assert result["revenue_reconciliation"]["status"] == "MATERIAL_VARIANCE"
    assert result["revenue_reconciliation"]["variance_bps"] == 2500


def test_reconciliation_kra_conflict():
    result = reconcile_declarations(
        declared_annual_revenue_cents=None,
        detected_annual_revenue_cents=0,
        declared_loans=None,
        detected_loan_drawdowns=[],
        declared_kra_compliant=True,
        detected_kra_compliance="NOT_DETECTED",
    )
    assert result["kra_reconciliation"]["status"] == "CONFLICT"


def test_reconciliation_no_floats():
    result = reconcile_declarations(
        declared_annual_revenue_cents=100_000_000_00,
        detected_annual_revenue_cents=97_000_000_00,
        declared_loans=None,
        detected_loan_drawdowns=[],
        declared_kra_compliant=True,
        detected_kra_compliance="COMPLIANT",
    )
    rev = result["revenue_reconciliation"]
    assert isinstance(rev["declared_cents"], int)
    assert isinstance(rev["detected_cents"], int)
    assert isinstance(rev["variance_cents"], int)
    assert isinstance(rev["variance_bps"], int)
    for v in rev.values():
        if v is not None:
            assert not isinstance(v, float), f"Float found: {v}"
