"""
Tests for Parity Review Suggestions Engine.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from suggestions import generate_suggestions


def test_suggestions_annual_revenue_included():
    txns = [
        {"role": "revenue_operational", "amount_cents": 1_000_000_00, "txn_date": "2024-01-01"},
    ]
    result = generate_suggestions(txns, enrichment=None, avg_monthly_inflow_cents=1_000_000_00)
    types = [s["type"] for s in result]
    assert "annual_revenue" in types


def test_suggestions_excludes_already_added():
    txns = [
        {"role": "revenue_operational", "amount_cents": 1_000_000_00, "txn_date": "2024-01-01"},
    ]
    enrichment = {"added_sections": ["annual_revenue"]}
    result = generate_suggestions(txns, enrichment=enrichment, avg_monthly_inflow_cents=1_000_000_00)
    types = [s["type"] for s in result]
    assert "annual_revenue" not in types


def test_suggestions_loan_drawdowns_surfaced():
    txns = [
        {"role": "loan_inflow", "amount_cents": 500_000_00, "txn_date": "2024-03-01", "entity_name": "Equity OD"},
    ]
    result = generate_suggestions(txns, enrichment=None, avg_monthly_inflow_cents=1_000_000_00)
    types = [s["type"] for s in result]
    assert "loan_drawdowns" in types


def test_suggestions_sorted_by_priority():
    txns = [
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2024-01-01"},
        {"role": "loan_inflow", "amount_cents": 500_000_00, "txn_date": "2024-01-02", "entity_name": "Bank"},
        {"role": "owner_distribution", "amount_cents": -200_000_00, "txn_date": "2024-01-03", "entity_name": "Director"},
    ]
    result = generate_suggestions(txns, enrichment=None, avg_monthly_inflow_cents=1_000_000_00)
    priorities = [s["priority"] for s in result]
    assert priorities == sorted(priorities)


def test_suggestions_no_floats_in_data():
    txns = [
        {"role": "revenue_operational", "amount_cents": 100_000_00, "txn_date": "2024-01-01"},
    ]
    result = generate_suggestions(txns, enrichment=None, avg_monthly_inflow_cents=100_000_00)

    def check_no_floats(obj):
        if isinstance(obj, float):
            raise AssertionError(f"Float found in suggestion data: {obj}")
        elif isinstance(obj, dict):
            for v in obj.values():
                check_no_floats(v)
        elif isinstance(obj, list):
            for item in obj:
                check_no_floats(item)

    for suggestion in result:
        check_no_floats(suggestion.get("data", {}))
