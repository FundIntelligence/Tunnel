"""
PAR-189 Stage 4 verification — Loan Activity Detected + Loan Facilities
extraction into build_snapshot_context().

Same caveat as Stages 1-3: the real acceptance bar is a byte-diff of
render_snapshot_html()'s HTML output on the real Deed document, old path vs
new. This file verifies the presentation dict (the combined loan_ctx dict
covering both "Loan Activity Detected" and "Loan Facilities" template
sections) is byte-identical between the ORIGINAL inline computation
(transcribed verbatim from the pre-Stage-4 source, i.e. PR #161/#162/#163's
merged state) and the NEW build_snapshot_context() + adapter path, across
fixture inputs chosen to hit every branch. The real-document diff is run
separately and is the actual acceptance-bar evidence.
"""
from __future__ import annotations

import pytest

from v1.analysis.snapshot_context import (
    _build_loan_activity,
    _resolve_recon_status,
)
from v1.analysis.snapshot_html_renderer import (
    _loan_activity_ctx_from,
    _status_to_badge,
)


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-4 source
# (backend/v1/analysis/snapshot_html_renderer.py as merged in PR #161/#162/#163).
# ─────────────────────────────────────────────────────────────────────────────

def _original_loan_ctx(txns, in_active_period, af, recon_available, loans_r, coverage_incomplete):
    repay_months = {}
    for t in txns:
        if t["role"] == "loan_repayment" and t["signed"] < 0:
            m = (t["txn_date"] or "")[:7]
            if in_active_period(m):
                repay_months[m] = repay_months.get(m, 0) + 1
    loan_freq = (
        sum(repay_months.values()) / len(repay_months) if repay_months else 0
    )
    loan_repayment_txn_count = sum(1 for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0)

    loan_disbursed_cents = sum(
        t["signed"] for t in txns if t["role"] == "loan_disbursement" and t["signed"] > 0
    )
    loan_repaid_cents = sum(
        t["abs"] for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0
    )
    loan_net_cents = loan_disbursed_cents - loan_repaid_cents

    loan_recon_status = loans_r.get("status") or ""
    fac_match_class, fac_match_label = _status_to_badge(loan_recon_status or "VARIANCE", coverage_incomplete)
    loan_facilities = [
        {
            "name":        fac.get("name") or "--",
            "amount_str":  _fmt_kes(fac.get("amount_cents") or 0),
            "match_class": fac_match_class,
            "match_label": fac_match_label,
        }
        for fac in (af.get("loan_breakdown") or [])
    ]

    loan_bank_net_str     = _fmt_kes(int(loans_r.get("bank_net_borrowing_kes", 0) * 100))
    loan_declared_net_str = _fmt_kes(int(loans_r.get("declared_net_borrowing_kes", 0) * 100))
    loan_var_raw          = loans_r.get("variance_pct")
    loan_variance_str     = f"{loan_var_raw:.1f}%" if loan_var_raw is not None else "0%"

    return {
        "loan_disbursed_str": _fmt_kes(loan_disbursed_cents),
        "loan_repaid_str":    _fmt_kes(loan_repaid_cents),
        "loan_net_str":       _fmt_kes(abs(loan_net_cents)),
        "loan_freq_str":      f"{loan_freq:.1f} txns / month",
        "loan_facility_count": loan_repayment_txn_count,
        "loan_facilities":    loan_facilities,
        "loan_recon_status":  loan_recon_status,
        "loan_bank_net_str":  loan_bank_net_str,
        "loan_declared_net_str": loan_declared_net_str,
        "loan_variance_str":  loan_variance_str,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _txn(role, signed, txn_date="2026-01-15"):
    return {"role": role, "signed": signed, "abs": abs(signed), "txn_date": txn_date}


_ALWAYS_ACTIVE = lambda m: True  # noqa: E731
_FY2026_ONLY = lambda m: m.startswith("2026-")  # noqa: E731

SCENARIOS = [
    pytest.param([], _ALWAYS_ACTIVE, {}, False, {}, False, id="no_txns_no_recon"),
    pytest.param(
        [_txn("loan_disbursement", 500000), _txn("loan_repayment", -50000, "2026-01-01"),
         _txn("loan_repayment", -50000, "2026-02-01")],
        _ALWAYS_ACTIVE, {}, False, {}, False, id="disbursement_and_repayments_no_recon",
    ),
    pytest.param(
        [_txn("loan_repayment", -20000, "2026-01-01")] * 3,
        _ALWAYS_ACTIVE,
        {"loan_breakdown": [{"name": "Facility A", "amount_cents": 1000000}]},
        True, {"status": "EXACT_MATCH", "bank_net_borrowing_kes": 500, "declared_net_borrowing_kes": 500, "variance_pct": 0.0},
        False, id="recon_exact_match",
    ),
    pytest.param(
        [_txn("loan_repayment", -20000, "2026-01-01")],
        _ALWAYS_ACTIVE,
        {"loan_breakdown": [{"name": "Facility A", "amount_cents": 200000}, {"name": "Facility B", "amount_cents": 300000}]},
        True, {"status": "HEALTHY", "bank_net_borrowing_kes": 1000, "declared_net_borrowing_kes": 900},
        False, id="raw_status_healthy_preserved_verbatim_resolves_acceptable_badge",
    ),
    pytest.param(
        [], _ALWAYS_ACTIVE,
        {"loan_breakdown": [{"name": "Facility A", "amount_cents": 100000}]},
        True, {},  # no status at all
        True, id="missing_status_coverage_incomplete_true",
    ),
    pytest.param(
        [], _ALWAYS_ACTIVE,
        {"loan_breakdown": [{"name": "Facility A", "amount_cents": 100000}]},
        True, {},  # no status at all
        False, id="missing_status_coverage_incomplete_false",
    ),
    pytest.param(
        [], _ALWAYS_ACTIVE,
        {"loan_breakdown": []},
        True, {"status": "VARIANCE", "variance_pct": None},
        False, id="variance_pct_none_shows_0pct_not_dash",
    ),
    pytest.param(
        [_txn("loan_repayment", -10000, None)],  # missing txn_date, no guard in original
        _ALWAYS_ACTIVE, {}, False, {}, False, id="missing_txn_date_no_guard_matches_original",
    ),
    pytest.param(
        [_txn("loan_repayment", -10000, "2025-12-01"), _txn("loan_repayment", -10000, "2026-01-01")],
        _FY2026_ONLY, {}, False, {}, False, id="active_period_filters_prior_year",
    ),
    pytest.param(
        [_txn("loan_repayment", -10000, "2026-01-01"), _txn("loan_disbursement", 200000, "2026-02-01")],
        _ALWAYS_ACTIVE,
        {"loan_breakdown": [{"amount_cents": None, "name": None}]},  # missing name/amount defaults
        True, {"status": "ACCEPTABLE_VARIANCE"},  # bank_net_borrowing_kes/declared_net_borrowing_kes keys absent -> default 0
        False, id="missing_facility_name_amount_and_bank_net_keys_absent",
    ),
]


@pytest.mark.parametrize("txns, in_active_period, af, recon_available, loans_r, coverage_incomplete", SCENARIOS)
def test_loan_activity_matches_original(txns, in_active_period, af, recon_available, loans_r, coverage_incomplete):
    old = _original_loan_ctx(txns, in_active_period, af, recon_available, loans_r, coverage_incomplete)
    new_typed = _build_loan_activity(txns, in_active_period, af, recon_available, loans_r, coverage_incomplete)
    new = _loan_activity_ctx_from(new_typed)
    assert new == old, f"Loan Activity/Facilities diverged.\nOLD: {old}\nNEW: {new}"


def test_explicit_none_bank_net_crashes_identically_old_and_new():
    """
    A real fidelity finding during Stage 4: an initial draft of
    _build_loan_activity() used `loans_r.get(key) or 0` (defensive), which
    silently diverges from the original's `loans_r.get(key, 0)` when the key
    is PRESENT with an explicit None value — the original raises TypeError
    there, `or 0` would not. Locking in that both paths crash identically
    rather than one silently "improving" on undefined original behavior.
    """
    loans_r = {"status": "VARIANCE", "bank_net_borrowing_kes": None}
    with pytest.raises(TypeError):
        _original_loan_ctx([], _ALWAYS_ACTIVE, {}, True, loans_r, False)
    with pytest.raises(TypeError):
        _build_loan_activity([], _ALWAYS_ACTIVE, {}, True, loans_r, False)


def test_resolve_recon_status_matches_status_to_badge_branches():
    """
    _resolve_recon_status() must partition status_raw/coverage_incomplete
    combinations identically to _status_to_badge()'s own branching, since the
    adapter's _RECON_STATUS_BADGE table only re-derives class/label from the
    resolved enum, not from the raw string again.
    """
    cases = [
        ("EXACT_MATCH", False, "EXACT_MATCH"),
        ("EXACT_MATCH", True, "EXACT_MATCH"),
        ("ACCEPTABLE", False, "ACCEPTABLE"),
        ("ACCEPTABLE_VARIANCE", False, "ACCEPTABLE"),
        ("HEALTHY", True, "ACCEPTABLE"),
        ("VARIANCE", True, "COVERAGE_GAP"),
        ("SOMETHING_ELSE", True, "COVERAGE_GAP"),
        ("VARIANCE", False, "VARIANCE"),
        ("", False, "VARIANCE"),
    ]
    for status_raw, coverage_incomplete, expected in cases:
        old_class, old_label = _status_to_badge(status_raw, coverage_incomplete)
        resolved = _resolve_recon_status(status_raw, coverage_incomplete)
        assert resolved == expected, f"{status_raw!r}/{coverage_incomplete} -> {resolved}, expected {expected}"
