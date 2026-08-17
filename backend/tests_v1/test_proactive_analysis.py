"""
Proactive analysis — unit tests.
Run with: python -m pytest tests_v1/test_proactive_analysis.py -v
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from v1.parity_review.proactive_analysis import generate_proactive_analysis
from v1.parity_review.context import (
    _build_txn_role_map,
    _tag_transactions,
    _compute_entity_breakdown,
    _compute_monthly_cashflow,
)

_REVENUE_ROLES  = frozenset({"revenue_operational", "revenue_non_operational"})
_SUPPLIER_ROLES = frozenset({"supplier_payment"})
_PAYROLL_ROLES  = frozenset({"payroll"})
_TAX_ROLES      = frozenset({"tax_payment", "kra_payment"})
_REVIEW_ROLES   = frozenset({"needs_review", "other"})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BUILDEX_CANONICAL = {
    "company_name": "Buildex Ltd",
    "transactions": [
        {"txn_id": "t001", "id": "t001", "signed_amount_cents": 109465000,
         "txn_date": "2025-02-10", "description": "Transfer from Joyce Mwanziu Avia"},
        {"txn_id": "t002", "id": "t002", "signed_amount_cents": 50000000,
         "txn_date": "2025-03-15", "description": "Payment received"},
        {"txn_id": "t003", "id": "t003", "signed_amount_cents": -200000000,
         "txn_date": "2025-04-01", "description": "RTGS: RTOBZN04517099"},
        {"txn_id": "t004", "id": "t004", "signed_amount_cents": -28733980,
         "txn_date": "2025-05-05", "description": "Loan repayment KCB"},
        {"txn_id": "t005", "id": "t005", "signed_amount_cents": -15000000,
         "txn_date": "2025-06-30", "description": "Salary payroll June"},
        {"txn_id": "t006", "id": "t006", "signed_amount_cents": -5000000,
         "txn_date": "2025-06-20", "description": "KRA tax payment"},
        {"txn_id": "t007", "id": "t007", "signed_amount_cents": 99900000,
         "txn_date": "2025-06-23", "description": "Peter Karanja A7F73Bce25E",
         "anomalies": [
             {"type": "POSSIBLE_CAPITAL_INJECTION", "severity": "CRITICAL",
              "reason": "Large inflow from rare entity with no reciprocal payments"}
         ]},
    ],
    "entities": [
        {"entity_id": "e001", "display_name": "Joyce Mwanziu Avia"},
        {"entity_id": "e002", "display_name": "Small Client Ltd"},
        {"entity_id": "e003", "display_name": "RTGS: RTOBZN04517099"},
        {"entity_id": "e004", "display_name": "KCB Bank"},
        {"entity_id": "e005", "display_name": "Staff Payroll"},
        {"entity_id": "e006", "display_name": "KRA"},
        {"entity_id": "e007", "display_name": "Peter Karanja A7F73Bce25E"},
    ],
    "txn_entity_map": [
        {"txn_id": "t001", "entity_id": "e001", "role": "revenue_operational"},
        {"txn_id": "t002", "entity_id": "e002", "role": "revenue_operational"},
        {"txn_id": "t003", "entity_id": "e003", "role": "supplier_payment"},
        {"txn_id": "t004", "entity_id": "e004", "role": "loan_repayment"},
        {"txn_id": "t005", "entity_id": "e005", "role": "payroll"},
        {"txn_id": "t006", "entity_id": "e006", "role": "tax_payment"},
        {"txn_id": "t007", "entity_id": "e007", "role": "needs_review"},
    ],
    "metrics": {
        "average_monthly_inflow_cents": 29994060,
        "average_monthly_outflow_cents": 29619165,
        "average_net_monthly_cents": 374895,
        "median_monthly_inflow_cents": 28000000,
        "revenue_growth_bps": -5140,
        "loan_repayment_burden_bps": 100,
        "payroll_stability": "SPARSE",
        "payroll_months_detected": 1,
        "kra_compliance": "PARTIAL",
        "statement_months": 12,
    },
    "currency": "KES",
}


def _build_deal_data(canonical=None):
    canonical = canonical or _BUILDEX_CANONICAL
    txn_role_map = _build_txn_role_map(canonical)
    entity_names = {
        str(e["entity_id"]): (e.get("display_name") or str(e["entity_id"]))
        for e in canonical["entities"]
    }
    tagged = _tag_transactions(canonical, txn_role_map, entity_names)
    monthly = _compute_monthly_cashflow(canonical)
    entity_breakdown = _compute_entity_breakdown(canonical, txn_role_map)

    top_suppliers = [r for r in entity_breakdown if r["role"] in _SUPPLIER_ROLES][:10]
    top_revenue   = [r for r in entity_breakdown if r["role"] in _REVENUE_ROLES][:10]
    review_ents   = [r for r in entity_breakdown if r["role"] in _REVIEW_ROLES][:20]

    loan_total = sum(
        abs(t["signed_amount_cents"]) for t in tagged
        if t["role"] == "loan_repayment" and t["signed_amount_cents"] < 0
    )
    payroll_months = len({
        t["txn_date"][:7] for t in tagged
        if t["role"] in _PAYROLL_ROLES and t["txn_date"] and len(t["txn_date"]) >= 7
    })
    tax_months = len({
        t["txn_date"][:7] for t in tagged
        if t["role"] in _TAX_ROLES and t["txn_date"] and len(t["txn_date"]) >= 7
    })

    return {
        "canonical": canonical,
        "tagged": tagged,
        "entity_names": entity_names,
        "monthly": monthly,
        "entity_breakdown": entity_breakdown,
        "top_suppliers": top_suppliers,
        "top_revenue": top_revenue,
        "review_ents": review_ents,
        "metrics": canonical["metrics"],
        "csi": canonical["metrics"],
        "loan_repayment_total_cents": loan_total,
        "payroll_months": payroll_months,
        "tax_months": tax_months,
        "n_months": canonical["metrics"]["statement_months"],
        "currency": "KES",
    }


@pytest.fixture
def deal_data():
    return _build_deal_data()


# ---------------------------------------------------------------------------
# Tests — generate_proactive_analysis (pure computation: figures/counts only)
#
# The advisory API (_identify_critical_issues / _identify_key_risks /
# _identify_strengths / _generate_recommendations) was intentionally removed in
# the "Parity Review pure computation rewrite" — Parity Review must surface
# computed data with no interpretation, recommendations, or advisory claims.
# These tests assert the current data-summary output and guard against any
# regression back to advisory language.
# ---------------------------------------------------------------------------

class TestGenerateProactiveAnalysis:
    def test_contains_data_summary_sections(self, deal_data):
        analysis = generate_proactive_analysis(deal_data)
        assert "Snapshot Data Summary" in analysis
        assert "## DEAL OVERVIEW" in analysis
        assert "## COMPUTED METRICS" in analysis
        assert "Ask a question to query the data." in analysis

    def test_markdown_table_formatted(self, deal_data):
        analysis = generate_proactive_analysis(deal_data)
        assert "##" in analysis
        assert "| Metric | Value |" in analysis

    def test_company_name_from_canonical(self, deal_data):
        analysis = generate_proactive_analysis(deal_data)
        assert "Buildex" in analysis

    def test_company_name_falls_back_when_absent(self):
        canonical = {**_BUILDEX_CANONICAL}
        canonical.pop("company_name", None)
        analysis = generate_proactive_analysis(_build_deal_data(canonical))
        assert "this deal" in analysis


class TestDealOverviewFigures:
    def test_transaction_counts_and_totals(self, deal_data):
        analysis = generate_proactive_analysis(deal_data)
        # 7 transactions: 3 credits, 4 debits (see _BUILDEX_CANONICAL)
        assert "| Total transactions | 7 |" in analysis
        assert "| Credit transactions | 3 |" in analysis
        assert "| Debit transactions | 4 |" in analysis
        assert "| Period | 12 months |" in analysis

    def test_computed_metrics_present(self, deal_data):
        analysis = generate_proactive_analysis(deal_data)
        assert "DSCR" in analysis
        assert "Revenue growth (H1 vs H2)" in analysis

    def test_top_entities_and_unclassified(self, deal_data):
        analysis = generate_proactive_analysis(deal_data)
        assert "## TOP ENTITIES" in analysis
        assert "Joyce Mwanziu Avia" in analysis          # top revenue source
        assert "## UNCLASSIFIED TRANSACTIONS" in analysis
        assert "Peter Karanja" in analysis                # needs_review entity


class TestPureComputationNoAdvisory:
    """Guards the Parity Review tone rule: no interpretation/advice/recommendations."""

    def test_no_advisory_language(self, deal_data):
        analysis = generate_proactive_analysis(deal_data)
        lowered = analysis.lower()
        for banned in ("recommend", "you should", "we advise", "critical issue",
                       "key risk", "strength", "🔴", "⚠️"):
            assert banned not in lowered, f"advisory language leaked: {banned!r}"


# ---------------------------------------------------------------------------
# Integration — proactive analysis on Buildex-like data
# ---------------------------------------------------------------------------

class TestProactiveIntegration:
    def test_buildex_analysis_surfaces_computed_figures(self, deal_data):
        analysis = generate_proactive_analysis(deal_data)

        assert "## DEAL OVERVIEW" in analysis
        assert "DSCR" in analysis
        assert "Revenue growth (H1 vs H2)" in analysis
        assert "Buildex" in analysis


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v", "--tb=short"])
