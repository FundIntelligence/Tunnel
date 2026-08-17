"""
Tests for the audited financials extractor — Buildex Interiors Company Ltd FY2025.

All cent values are independently verified against the source PDF:
  tests/fixtures/buildex/buildex_financials_2025.pdf  (24 pages, 749 KB)
"""
from __future__ import annotations

import os
import pytest

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "buildex", "buildex_financials_2025.pdf"
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def result():
    """Run the extractor once and share across all tests in this module."""
    from app.extractors.audited_financials_extractor import extract_audited_financials
    return extract_audited_financials(FIXTURE_PATH)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Metadata
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadata:
    def test_company_name(self, result):
        assert "BUILDEX" in result["company_name"].upper()

    def test_financial_year(self, result):
        assert result["financial_year"] == 2025

    def test_currency(self, result):
        assert result["currency"] == "KES"

    def test_currency_not_sourced_from_cover_page_alone(self):
        """
        Regression guard: the Buildex cover page (page 1) carries no currency
        marker at all — "KShs" only appears in the accounting-policy note
        (page 13) and the explicit currency note (page 24). If metadata
        extraction ever goes back to scanning page 1 only, this must fail
        loudly instead of silently returning currency=None.
        """
        import pdfplumber
        from app.extractors.currency_detector import detect as detect_currency

        with pdfplumber.open(FIXTURE_PATH) as pdf:
            page_1_text = pdf.pages[0].extract_text() or ""
            assert detect_currency(page_1_text) is None, (
                "Test fixture assumption changed: page 1 now contains a "
                "currency marker. Re-check this regression guard still makes sense."
            )

    def test_financial_year_end(self, result):
        assert result["financial_year_end"] == "2025-12-31"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Income Statement
# ─────────────────────────────────────────────────────────────────────────────

class TestIncomeStatement:
    def test_turnover(self, result):
        assert result["turnover_cents"] == 37_206_227_700

    def test_cost_of_sales(self, result):
        assert result["cost_of_sales_cents"] == 32_700_728_500

    def test_operating_costs(self, result):
        assert result["operating_costs_cents"] == 918_972_200

    def test_administrative_costs(self, result):
        assert result["administrative_costs_cents"] == 947_518_800

    def test_staff_costs(self, result):
        assert result["staff_costs_cents"] == 1_430_528_300

    def test_finance_costs(self, result):
        assert result["finance_costs_cents"] == 375_461_300

    def test_profit_before_tax(self, result):
        assert result["profit_before_tax_cents"] == 833_018_500

    def test_tax_expense(self, result):
        assert result["tax_expense_cents"] == 288_252_000

    def test_profit_after_tax(self, result):
        assert result["profit_after_tax_cents"] == 544_766_500

    def test_pat_equals_pbt_minus_tax(self, result):
        """Integrity check: PAT = PBT − Tax (within KES 1)."""
        expected = result["profit_before_tax_cents"] - result["tax_expense_cents"]
        assert abs(expected - result["profit_after_tax_cents"]) <= 100


# ─────────────────────────────────────────────────────────────────────────────
# 3. Balance Sheet
# ─────────────────────────────────────────────────────────────────────────────

class TestBalanceSheet:
    def test_ppe(self, result):
        assert result["property_plant_equipment_cents"] == 1_438_478_500

    def test_inventory(self, result):
        assert result["inventory_cents"] == 2_911_841_500

    def test_cash_and_equivalents(self, result):
        assert result["cash_and_equivalents_cents"] == 212_578_100

    def test_trade_receivables(self, result):
        assert result["trade_receivables_cents"] == 563_654_800

    def test_total_assets(self, result):
        assert result["total_assets_cents"] == 5_887_482_900

    def test_trade_payables(self, result):
        assert result["trade_payables_cents"] == 1_572_435_100

    def test_long_term_loans(self, result):
        assert result["long_term_loans_cents"] == 2_032_717_500

    def test_retained_earnings(self, result):
        assert result["retained_earnings_cents"] == 1_984_078_300

    def test_share_capital(self, result):
        assert result["share_capital_cents"] == 10_000_000


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cash Flow Statement
# ─────────────────────────────────────────────────────────────────────────────

class TestCashFlow:
    def test_operating_cashflow(self, result):
        assert result["operating_cashflow_cents"] == 477_242_200

    def test_investing_cashflow(self, result):
        assert result["investing_cashflow_cents"] == -1_109_330_000

    def test_financing_cashflow(self, result):
        assert result["financing_cashflow_cents"] == 255_709_200

    def test_cash_at_start(self, result):
        assert result["cash_at_start_cents"] == 588_956_700

    def test_cash_at_end(self, result):
        assert result["cash_at_end_cents"] == 212_578_100

    def test_cashflow_reconciles(self, result):
        """Net activities ≈ ending cash − opening cash (within 2%)."""
        net = (
            result["operating_cashflow_cents"]
            + result["investing_cashflow_cents"]
            + result["financing_cashflow_cents"]
        )
        net_bal = result["cash_at_end_cents"] - result["cash_at_start_cents"]
        tol = max(abs(net_bal) * 0.02, 200)
        assert abs(net - net_bal) <= tol


# ─────────────────────────────────────────────────────────────────────────────
# 5. Note 11 — Cash Breakdown
# ─────────────────────────────────────────────────────────────────────────────

class TestCashBreakdown:
    def test_cash_breakdown_present(self, result):
        assert result["cash_breakdown"] is not None

    def test_absa(self, result):
        assert result["cash_breakdown"]["Absa"] == 23_539_700

    def test_equity(self, result):
        # Includes Equity Bank Account 2 (KES 310) — both accounts at Equity Bank
        assert result["cash_breakdown"]["Equity"] == 155_618_200

    def test_kcb(self, result):
        assert result["cash_breakdown"]["KCB"] == 30_312_500

    def test_zemo(self, result):
        assert result["cash_breakdown"]["Zemo"] == 3_107_600

    def test_cash_breakdown_total_matches_bs(self, result):
        """Sum of Note 11 items reconciles to BS cash within KES 1."""
        total = sum(result["cash_breakdown"].values())
        bs_cash = result["cash_and_equivalents_cents"]
        assert abs(total - bs_cash) <= 100


# ─────────────────────────────────────────────────────────────────────────────
# 6. Note 14 — Loan Breakdown
# ─────────────────────────────────────────────────────────────────────────────

class TestLoanBreakdown:
    def test_loan_breakdown_present(self, result):
        assert result["loan_breakdown"] is not None

    def test_five_facilities(self, result):
        assert len(result["loan_breakdown"]) == 5

    def test_loan_total_matches_bs(self, result):
        """Sum of Note 14 loans matches BS long-term loans exactly."""
        total = sum(item["amount_cents"] for item in result["loan_breakdown"])
        assert total == result["long_term_loans_cents"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. Extraction Quality
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractionQuality:
    def test_confidence_100(self, result):
        assert float(result["extraction_confidence"]) == 100.0

    def test_sha256_present(self, result):
        assert len(result["sha256_hash"]) == 64

    def test_extraction_method(self, result):
        assert result["extraction_method"] == "pdfplumber_coordinate"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Determinism
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_idempotent_extraction(self, result):
        """Extracting the same PDF twice must produce the same SHA-256 — determinism guard."""
        from app.extractors.audited_financials_extractor import extract_audited_financials
        result2 = extract_audited_financials(FIXTURE_PATH)
        assert result["sha256_hash"] == result2["sha256_hash"]

    def test_numeric_fields_are_integers(self, result):
        """All cent-denominated fields must be plain ints — no floats allowed."""
        int_fields = [
            "turnover_cents", "cost_of_sales_cents", "profit_before_tax_cents",
            "profit_after_tax_cents", "total_assets_cents", "cash_and_equivalents_cents",
            "long_term_loans_cents",
        ]
        for field in int_fields:
            val = result.get(field)
            if val is not None:
                assert isinstance(val, int), f"{field} is {type(val).__name__}, expected int"
