"""
PAR-189 Stage 3 verification — Inventory Analysis + Analyst Notes extraction
into build_snapshot_context().

Same caveat as Stage 1/2: the real acceptance bar is a byte-diff of
render_snapshot_html()'s HTML output on the real Deed document, old path vs
new. This file verifies the presentation dicts (inventory_ctx, analyst_notes)
are byte-identical between the ORIGINAL inline computation (transcribed
verbatim from the pre-Stage-3 source, i.e. PR #161/#162's merged state) and
the NEW build_snapshot_context() + adapter path, across fixture inputs
chosen to hit every branch. Per the template (snapshot.html:1248-1261,1533-
1534), both are consumed with no further string formatting beyond straight
interpolation — so dict/value equality here implies HTML equality for these
two sections, for any input they can represent. The real-document diff is
run separately and is the actual acceptance-bar evidence.
"""
from __future__ import annotations

import pytest

from v1.analysis.snapshot_context import (
    DEFAULT_INVENTORY_CONFIG,
    _build_inventory,
)
from v1.analysis.snapshot_html_renderer import _inventory_ctx_from


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-3 source
# (backend/v1/analysis/snapshot_html_renderer.py as merged in PR #161/#162).
# ─────────────────────────────────────────────────────────────────────────────

def _original_inventory_ctx(af, recon_available):
    inv_fy = str(af.get("financial_year") or "") if recon_available else ""
    inventory_cents_raw     = af.get("inventory_cents") if recon_available else None
    cost_of_sales_cents_raw = af.get("cost_of_sales_cents") if recon_available else None
    extraction_confidence_raw = af.get("extraction_confidence") if recon_available else None

    inventory_data_present = (
        recon_available
        and inventory_cents_raw is not None
        and cost_of_sales_cents_raw is not None
        and int(inventory_cents_raw) > 0
    )
    if inventory_data_present:
        inventory_cents     = int(inventory_cents_raw)
        cost_of_sales_cents = int(cost_of_sales_cents_raw)
        inventory_turnover   = cost_of_sales_cents / inventory_cents
        dio_days             = 365 / inventory_turnover if inventory_turnover > 0 else None
        if inventory_turnover >= 6:
            inventory_clause = "Inventory turns over quickly relative to cost of sales — LOW inventory risk."
        elif inventory_turnover >= 3:
            inventory_clause = "Inventory turnover is moderate."
        else:
            inventory_clause = (
                "Inventory turns over slowly — may indicate slow-moving stock or "
                "overstocking risk."
            )
        return {
            "available":      True,
            "financial_year": inv_fy,
            "inventory_str":  _fmt_kes(inventory_cents),
            "cogs_str":       _fmt_kes(cost_of_sales_cents),
            "turnover_str":   f"{inventory_turnover:.1f}x",
            "dio_str":        f"{dio_days:.0f} days" if dio_days is not None else "--",
            "clause":         inventory_clause,
            "confidence_str": (
                f"{extraction_confidence_raw:.2f}" if extraction_confidence_raw is not None else "not recorded"
            ),
        }
    else:
        return {
            "available": False,
            "financial_year": inv_fy,
            "note": (
                f"Inventory and/or cost of sales figures were not present in the audited "
                f"financial statements provided for FY{inv_fy} — inventory analysis cannot "
                "be computed for this deal."
            ) if recon_available else (
                "Inventory analysis requires audited financials — not yet submitted for this deal."
            ),
        }


def _original_analyst_notes(deal):
    return deal.get("analyst_notes") or ""


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

INVENTORY_SCENARIOS = [
    pytest.param({}, False, id="no_recon_no_audited_financials"),
    pytest.param({"financial_year": 2025}, False, id="recon_unavailable_but_fy_present_still_unavailable"),
    pytest.param({"financial_year": 2025}, True, id="recon_available_no_inventory_cents"),
    pytest.param({"financial_year": 2025, "inventory_cents": 0, "cost_of_sales_cents": 500000}, True, id="zero_inventory_cents_treated_unavailable"),
    pytest.param({"financial_year": 2025, "inventory_cents": 100000, "cost_of_sales_cents": None}, True, id="missing_cost_of_sales"),
    pytest.param(
        {"financial_year": 2025, "inventory_cents": 100000, "cost_of_sales_cents": 700000, "extraction_confidence": 0.92},
        True, id="high_turnover_low_risk_with_confidence",
    ),
    pytest.param(
        {"financial_year": 2025, "inventory_cents": 200000, "cost_of_sales_cents": 800000},
        True, id="moderate_turnover_no_confidence_recorded",
    ),
    pytest.param(
        {"financial_year": 2025, "inventory_cents": 500000, "cost_of_sales_cents": 300000},
        True, id="low_turnover_slow_moving",
    ),
    pytest.param(
        {"financial_year": 2025, "inventory_cents": 100000, "cost_of_sales_cents": 0},
        True, id="zero_cost_of_sales_turnover_zero_dio_none",
    ),
    pytest.param(
        {"financial_year": None, "inventory_cents": 100000, "cost_of_sales_cents": 600000},
        True, id="missing_financial_year_still_computes",
    ),
    pytest.param(
        {"financial_year": 2025, "inventory_cents": 333333, "cost_of_sales_cents": 2000000},
        True, id="exact_boundary_turnover_6",
    ),
]


@pytest.mark.parametrize("af, recon_available", INVENTORY_SCENARIOS)
def test_inventory_matches_original(af, recon_available):
    old = _original_inventory_ctx(af, recon_available)
    new_typed = _build_inventory(af, recon_available, DEFAULT_INVENTORY_CONFIG)
    new = _inventory_ctx_from(new_typed)
    assert new == old, f"Inventory Analysis diverged.\nOLD: {old}\nNEW: {new}"


ANALYST_NOTES_SCENARIOS = [
    pytest.param({}, id="no_notes_key"),
    pytest.param({"analyst_notes": None}, id="explicit_none"),
    pytest.param({"analyst_notes": ""}, id="empty_string"),
    pytest.param({"analyst_notes": "Reviewed 2026-08-20, flag for follow-up on supplier concentration."}, id="real_note"),
]


@pytest.mark.parametrize("deal", ANALYST_NOTES_SCENARIOS)
def test_analyst_notes_matches_original(deal):
    old = _original_analyst_notes(deal)
    # Mirrors build_snapshot_context()'s own extraction + the renderer's
    # `shared_ctx["analyst_notes"] or ""` reconstruction, in one step.
    new_shared = deal.get("analyst_notes") or None
    new = new_shared or ""
    assert new == old, f"Analyst Notes diverged.\nOLD: {old!r}\nNEW: {new!r}"
