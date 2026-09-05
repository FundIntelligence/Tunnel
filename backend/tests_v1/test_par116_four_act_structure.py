"""
PAR-116 — four-act restructure content-completeness + ordering checks.

This is a reordering/regrouping-only PR: every section, table, and disclosure
present before it must still be present and unchanged in content after it —
only position/grouping changes (plus the PAR-118 Transaction Pattern Analysis
/ Observed Patterns merge, and the PAR-116 4-point reconciliation row reorder
to Revenue, Expenses, Loan activity, Cash position).

Verification follows PAR-189's own precedent: drive the real
_build_four_point_reconciliation() / _four_point_recon_ctx_from() functions
with real, messy, low-confidence deal data (Buildex Ltd,
deal_id=4f4f4cba-d688-4b9c-a887-71a0dd6b83d5, FY2025 — the same deal PAR-207/
PAR-209 already confirmed against live prod: a MATERIAL account-coverage gap,
87.47%, 2 of 4 declared accounts submitted, and the known, tracked Loan
Activity sign-flip variance) rather than hand-typing recon_rows, and render
the actual Jinja template end to end. Not a synthetic/clean mock.

PAR-117 (validating coverage-first sequencing against a high-coverage,
low-confidence-for-other-reasons deal) is a separate, not-yet-done
validation — not covered here.
"""
import os
import sys

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from jinja2 import Environment, FileSystemLoader

from backend.v1.analysis.snapshot_context import (
    _build_four_point_reconciliation,
    DEFAULT_RECON_CHECK_CONFIG,
)
from backend.v1.analysis.snapshot_html_renderer import _four_point_recon_ctx_from

_TEMPLATES_DIR = os.path.join(_BACKEND, "v1", "templates")

# Real recon_section for Buildex Ltd FY2025 (deal_id=4f4f4cba-d688-4b9c-a887-71a0dd6b83d5),
# captured during PAR-207's live prod correctness check.
_REAL_RECON_SECTION = {
    "cash_position": {
        "status": "ACCEPTABLE_VARIANCE", "variance_pct": 1.14,
        "total_bank_kes": 2150019.47, "total_declared_kes": 2125781.00,
    },
    "revenue": {
        "gap_pct": 22.92,
        "assessment": "RISK — revenue gap too large (>15%)",
        "bank_inflows_kes": 286796695.35, "declared_revenue_kes": 372062277.00,
        "fiscal_period": "2025-01-01 to 2025-12-31",
    },
    "expenses": {
        "gap_pct": 18.15,
        "explanation": "Gap explained by: non-cash expenses (depreciation, "
                        "amortisation), accrued payables, inventory build, "
                        "and opening accruals",
        "bank_outflows_kes": 297715131.98, "declared_expenses_kes": 363732091.00,
    },
    "loan_activity": {
        "status": "VARIANCE", "variance_pct": -236.7,
        "bank_net_borrowing_kes": -3495696.00, "declared_net_borrowing_kes": 2557092.00,
    },
}


def _real_recon_rows():
    """Drives the real production reconciliation-row builder against real Buildex data."""
    fpr = _build_four_point_reconciliation(
        recon_section=_REAL_RECON_SECTION,
        recon_available=True,
        coverage_incomplete=True,  # MATERIAL coverage gap on this deal
        missing_note="Absa and Zemo bank statements not submitted.",
        fy=2025,
        currency="KES",
        config=DEFAULT_RECON_CHECK_CONFIG,
    )
    return _four_point_recon_ctx_from(fpr)


def test_four_point_reconciliation_row_order_is_revenue_expenses_loan_cash():
    recon_ctx = _real_recon_rows()
    checks = [r["check"] for r in recon_ctx["recon_rows"]]
    assert checks == ["Revenue", "Expenses", "Loan activity", "Cash position"]


def _minimal_render_ctx(recon_available: bool, recon_rows=None, recon_fiscal_note=""):
    """Every template variable render_snapshot_html's context ever supplies —
    kept minimal/dummy except recon_rows, which uses the real builder above
    when recon_available=True."""
    return dict(
        view="observed_recon", partner_name=None, company_name="Buildex Ltd",
        sector="Trade", period_label="Jan-Dec 2025", generated_date="2026-08-31",
        analyst_notes="notes", report_id="RPT-1", sha256_hash="a" * 64,
        qr_svg="<svg></svg>", verify_url="https://x", currency="KES",
        recon_available=recon_available, recon_tier="LOW_CONFIDENCE",
        vp_confidence_color="warning", loan_recon_label="Variance",
        tier_badge_class="tier-low", tier_badge_text="Observed",
        data_source_pills=[{"label": "Bank statement", "active": True}],
        data_source_note="note", total_txn_count=12851,
        kms=[{"label": "Revenue", "value": "KES 1", "sub": "sub", "color_class": ""}],
        cashflow_rows=[{"month_label": "Jan", "inflow_str": "1", "outflow_str": "1",
                         "net_color_class": "pos", "bar_pct": 10, "net_str": "1"}],
        cashflow_note="note", cashflow_peak_trough_note="", cashflow_trend_note="",
        inflow_total_str="KES 1", inflow_segments=[{"label": "x", "pct": 10, "amount_str": "1"}],
        inflow_warn="", outflow_total_str="KES 1",
        outflow_segments=[{"label": "x", "pct": 10, "amount_str": "1"}], outflow_warn="",
        tax_count=1, tax_freq_str="1/mo", tax_penalty_count=0, tax_jan_spike_str="",
        tax_total_str="KES 1", tax_note="note",
        loan_disbursed_str="KES 1", loan_repaid_str="KES 1", loan_net_str="1",
        loan_freq_str="1/mo", loan_facility_count=1,
        loan_facilities=[{"name": "Facility A", "amount_str": "KES 1", "match_class": "b-ok",
                           "match_label": "Matched"}],
        loan_recon_status="VARIANCE", loan_bank_net_str="KES 1", loan_declared_net_str="KES 2",
        loan_variance_str="1.0%",
        recon_rows=recon_rows or [], recon_fiscal_note=recon_fiscal_note,
        patterns=[{"tag": "TAG", "name": "Pattern", "data_statement": "stmt",
                   "check_prompt": "check"}],
        account_coverage={
            "available": True, "advisory_tier": "MATERIAL", "coverage_pct": 87.47,
            "submitted_count": 2, "declared_count": 4, "missing_balance_str": "KES 1",
            "coverage_color_class": "warn",
            "accounts": [{"bank_name": "KCB", "declared_str": "KES 1",
                          "status_class": "status-matched", "status_label": "Submitted",
                          "materiality_class": "status-matched", "materiality": "MATERIAL"}],
            "recommendation": "rec", "note": "",
        },
        inventory={"available": False, "financial_year": "2025", "note": "No inventory data."},
        supplier_payments={"available": True, "total_str": "KES 1", "txn_count": 1,
                            "entity_count": 1, "top_name": "Sup", "top_pct_str": "10.0%",
                            "clause": "clause"},
        tax_compliance={"total_str": "KES 1", "n_tax_months": 1, "n_total_months": 12,
                         "kra_compliance": "COMPLIANT", "clause": "clause"},
        transaction_patterns={"critical_count": 0, "high_count": 1, "total_flagged": 1,
                               "total_txn_count": 12851, "clause": "clause"},
        inter_account_transfer={"badge_label": "Not Available", "pairs": [],
                                 "note": "note", "override_note": ""},
        risk_assessment={"tier": "LOW_CONFIDENCE", "advisory_tier": "MATERIAL",
                          "missing_pct": "12.5", "largest_rev_pct_str": "10.0%",
                          "anomaly_summary": "summary", "conclusion": "conclusion",
                          "transfer_note": "transfer"},
    )


@pytest.fixture(scope="module")
def _template():
    env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR))
    return env.get_template("snapshot.html")


def test_acts_render_in_order_recon_available(_template):
    recon_ctx = _real_recon_rows()
    ctx = _minimal_render_ctx(
        True, recon_rows=recon_ctx["recon_rows"],
        recon_fiscal_note=recon_ctx["recon_fiscal_note"],
    )
    html = _template.render(**ctx)
    positions = [html.index(t) for t in (
        "Act 1 — Orientation", "Act 2 — Core Reconciliation",
        "Act 3 — Supporting Diagnostics", "Act 4 — Synthesis",
    )]
    assert positions == sorted(positions)


def test_acts_render_in_order_recon_unavailable(_template):
    ctx = _minimal_render_ctx(False)
    html = _template.render(**ctx)
    positions = [html.index(t) for t in (
        "Act 1 — Orientation", "Act 2 — Core Reconciliation",
        "Act 3 — Supporting Diagnostics", "Act 4 — Synthesis",
    )]
    assert positions == sorted(positions)


# Every section present in the pre-PAR-116 template, keyed by its .sec-label
# heading text (or, for the Observed Patterns merge, its preserved sub-line).
_EXPECTED_HEADINGS_BOTH_STATES = [
    "Key Metrics", "Data Submitted", "Account Coverage — Declared vs Submitted",
    "Transaction Pattern Analysis", "Observed Patterns — For Analyst Review",
    "Supplier Payment Analysis", "Inter-Account Transfer Analysis",
    "Tax Compliance Analysis", "Monthly Cashflow", "Analyst Notes",
    "Risk Assessment Summary",
]
_EXPECTED_HEADINGS_RECON_AVAILABLE = [
    "4-Point Reconciliation", "Inflow + Outflow Composition",
    "Loan Facilities — Declared vs Bank", "Inventory Analysis",
]
_EXPECTED_HEADINGS_RECON_UNAVAILABLE = [
    "Reconciliation", "Loan Activity Detected", "Tax Payment Pattern",
    "Inflow Composition", "Outflow Composition",
]


def test_content_completeness_recon_available(_template):
    recon_ctx = _real_recon_rows()
    ctx = _minimal_render_ctx(
        True, recon_rows=recon_ctx["recon_rows"],
        recon_fiscal_note=recon_ctx["recon_fiscal_note"],
    )
    html = _template.render(**ctx)
    for heading in _EXPECTED_HEADINGS_BOTH_STATES + _EXPECTED_HEADINGS_RECON_AVAILABLE:
        assert heading in html, f"missing section: {heading!r}"


def test_content_completeness_recon_unavailable(_template):
    ctx = _minimal_render_ctx(False)
    html = _template.render(**ctx)
    for heading in _EXPECTED_HEADINGS_BOTH_STATES + _EXPECTED_HEADINGS_RECON_UNAVAILABLE:
        assert heading in html, f"missing section: {heading!r}"


def test_account_coverage_precedes_reconciliation_act(_template):
    """Act 1 (Data Submitted -> Account Coverage) must fully precede Act 2's
    4-point reconciliation content — the core PAR-116 reorder."""
    recon_ctx = _real_recon_rows()
    ctx = _minimal_render_ctx(
        True, recon_rows=recon_ctx["recon_rows"],
        recon_fiscal_note=recon_ctx["recon_fiscal_note"],
    )
    html = _template.render(**ctx)
    assert html.index("Account Coverage") < html.index("4-Point Reconciliation")


def test_loan_facilities_immediately_follows_loan_activity_row(_template):
    """PAR-116: 'Loan Facilities table immediately follows Loan Activity.'
    The reconciliation table is split around Composition (Revenue, Expenses |
    Loan activity, Cash position), so Loan Facilities must appear right after
    the second table half, before Cash position's own containing table close —
    concretely: after 'Loan activity' row text and before Act 3 starts."""
    recon_ctx = _real_recon_rows()
    ctx = _minimal_render_ctx(
        True, recon_rows=recon_ctx["recon_rows"],
        recon_fiscal_note=recon_ctx["recon_fiscal_note"],
    )
    html = _template.render(**ctx)
    idx_loan_row = html.index(">Loan activity<")
    idx_loan_facilities = html.index("Loan Facilities — Declared vs Bank")
    idx_act3 = html.index("Act 3 — Supporting Diagnostics")
    assert idx_loan_row < idx_loan_facilities < idx_act3


def test_analyst_notes_immediately_precedes_risk_assessment(_template):
    ctx = _minimal_render_ctx(False)
    html = _template.render(**ctx)
    # Match the rendered heading + badge markup itself, not explanatory HTML
    # comments (which also render into output and can contain either phrase).
    idx_notes = html.index('>Analyst Notes <span class="sec-label-badge">')
    idx_risk = html.index('>Risk Assessment Summary <span class="sec-label-badge">')
    assert idx_notes < idx_risk
    # nothing but the act-title should sit between them
    between = html[idx_notes:idx_risk]
    assert between.count('class="sec-label"') == 1  # only Analyst Notes' own label
