"""
Regression: expense reconciliation must use the income statement's OWN stated
total-expenses figure (total_expenses_cents) as the comparison input, NOT the
sum of the five granular cost sub-categories.

Guards the Fix A invariant: sub-category sum != reconciliation input whenever a
stated total is present, with a documented fallback to the sub-category sum only
when no stated total exists (legacy extractor / pre-migration-018 rows).
"""
import os
import sys

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import backend.v1.analysis.reconciliation_engine as re_engine

# Granular sub-categories sum to 1,500 cents; the document's stated total is
# deliberately different so the two inputs cannot be confused.
_SUBCATEGORY_FIELDS = {
    "cost_of_sales_cents": 100,
    "operating_costs_cents": 200,
    "administrative_costs_cents": 300,
    "staff_costs_cents": 400,
    "finance_costs_cents": 500,
}
_SUBCATEGORY_SUM_CENTS = sum(_SUBCATEGORY_FIELDS.values())  # 1500


def _af(**overrides):
    af = {
        "financial_year_start": "2025-01-01",
        "financial_year_end": "2025-12-31",
        **_SUBCATEGORY_FIELDS,
    }
    af.update(overrides)
    return af


def test_uses_stated_total_not_subcategory_sum(monkeypatch):
    af = _af(total_expenses_cents=9_999)  # != 1500
    monkeypatch.setattr(re_engine, "_get_audited_financials", lambda deal_id: af)
    monkeypatch.setattr(
        re_engine, "_get_fiscal_year_transactions", lambda deal_id, s, e: []
    )

    result = re_engine.calculate_expense_reconciliation("deal-1")

    assert result["declared_expenses_source"] == "stated_total"
    # 9,999 cents -> 99.99 KES (the stated total)
    assert result["declared_expenses_kes"] == 99.99
    # Critically: NOT the sub-category sum (1,500 cents -> 15.00 KES)
    assert result["declared_expenses_kes"] != round(_SUBCATEGORY_SUM_CENTS / 100, 2)


def test_falls_back_to_subcategory_sum_when_no_stated_total(monkeypatch):
    af = _af(total_expenses_cents=None)  # legacy / pre-migration row
    monkeypatch.setattr(re_engine, "_get_audited_financials", lambda deal_id: af)
    monkeypatch.setattr(
        re_engine, "_get_fiscal_year_transactions", lambda deal_id, s, e: []
    )

    result = re_engine.calculate_expense_reconciliation("deal-1")

    assert result["declared_expenses_source"] == "subcategory_sum"
    assert result["declared_expenses_kes"] == round(_SUBCATEGORY_SUM_CENTS / 100, 2)


def test_stated_total_of_zero_is_authoritative_not_fallback(monkeypatch):
    # A document that genuinely states zero expenses must use 0, not silently
    # fall back to summing sub-categories (0 is not None).
    af = _af(total_expenses_cents=0)
    monkeypatch.setattr(re_engine, "_get_audited_financials", lambda deal_id: af)
    monkeypatch.setattr(
        re_engine, "_get_fiscal_year_transactions", lambda deal_id, s, e: []
    )

    result = re_engine.calculate_expense_reconciliation("deal-1")

    assert result["declared_expenses_source"] == "stated_total"
    assert result["declared_expenses_kes"] == 0.0
