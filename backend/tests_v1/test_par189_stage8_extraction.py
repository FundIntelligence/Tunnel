"""
PAR-189 Stage 8 verification — Account Coverage extraction into
build_snapshot_context(), plus the coverage-percentage formatting fix.

Same pattern as Stages 1-7: the real acceptance bar is a full-document
byte-diff of render_snapshot_html()'s output on the real Deed document, old
path vs new (run separately; PASS, byte-identical, reported on PAR-189).

Two things carry extra weight here:

1. Deed has no audited financials, so it renders Account Coverage's
   UNAVAILABLE branch. The POPULATED branch was verified separately against
   10 real prod deals by driving the real calculate_account_coverage() (see
   the Stage 8 report), and is additionally covered by the scenarios below.

2. test_coverage_pct_round_trip_matches_original_for_every_possible_value
   locks in a REAL divergence this stage found and fixed. Storing an already-
   rounded percentage as a 0-1 fraction and multiplying back by 100 changes
   the rendered digit for 45 of the 10,001 possible values. Stage 1's Risk
   Assessment adapter had shipped that naive form since PR #161; every
   stage's byte-diff missed it because Deed renders "--" for coverage.
"""
from __future__ import annotations

import pytest

from v1.analysis.snapshot_context import (
    ACCOUNT_COVERAGE_UNAVAILABLE_NOTE,
    AccountCoverage,
    Money,
    Percent,
    RiskAssessment,
    _build_account_coverage,
)
from v1.analysis.snapshot_html_renderer import (
    _account_coverage_ctx_from,
    _fmt_pct_1dp,
    _risk_assessment_ctx_from,
)


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-8 source
# (snapshot_html_renderer.py as merged at 4826403).
# ─────────────────────────────────────────────────────────────────────────────

_AC_STAT_COLOR = {
    "NEGLIGIBLE": "ok", "MINOR": "warn", "MATERIAL": "warn", "CRITICAL": "critical",
}
_AC_MATERIALITY_PILL = {
    "NEGLIGIBLE": "status-matched", "MINOR": "status-matched",
    "MATERIAL": "status-critical", "CRITICAL": "status-critical",
}


def _original_account_coverage(acct_cov_raw):
    if acct_cov_raw.get("coverage_pct") is not None:
        return {
            "available":        True,
            "coverage_pct":     f"{acct_cov_raw.get('coverage_pct', 0):.1f}",
            "coverage_color_class": _AC_STAT_COLOR.get(acct_cov_raw.get("advisory_tier"), "critical"),
            "declared_count":   acct_cov_raw.get("declared_accounts_count", 0),
            "submitted_count":  acct_cov_raw.get("submitted_accounts_count", 0),
            "missing_count":    acct_cov_raw.get("missing_accounts_count", 0),
            "missing_balance_str": _fmt_kes(int(acct_cov_raw.get("missing_balance_cents") or 0)),
            "advisory_tier":    acct_cov_raw.get("advisory_tier", "--"),
            "recommendation":   acct_cov_raw.get("recommendation", ""),
            "accounts": [
                {
                    "bank_name":    a.get("bank_name") or "--",
                    "declared_str": _fmt_kes(int(a.get("declared_balance_cents") or 0)),
                    "status_label": "✓ Submitted" if a.get("status") == "SUBMITTED" else "Missing",
                    "status_class": "status-matched" if a.get("status") == "SUBMITTED" else "status-missing",
                    "materiality":  a.get("materiality") or "--",
                    "materiality_class": _AC_MATERIALITY_PILL.get(a.get("materiality"), "status-critical"),
                }
                for a in (acct_cov_raw.get("account_details") or [])
            ],
        }
    return {
        "available": False,
        "note": (
            "Account coverage compares the bank accounts declared in audited "
            "financials (Note 11 cash breakdown) against the statements "
            "submitted. Submit audited financials to populate this advisory."
        ),
    }


def _assert_equivalent(raw):
    original = _original_account_coverage(raw)
    new = _account_coverage_ctx_from(_build_account_coverage(raw, "KES"))
    assert new == original
    return new


def _acct(bank, cents, status, materiality):
    return {
        "bank_name": bank,
        "declared_balance_cents": cents,
        "status": status,
        "materiality": materiality,
    }


def _raw(**over):
    base = {
        "coverage_pct": 87.47,
        "declared_accounts_count": 4,
        "submitted_accounts_count": 2,
        "missing_accounts_count": 2,
        "missing_balance_cents": 1_250_000,
        "advisory_tier": "MATERIAL",
        "recommendation": "Strongly recommend uploading missing statements before finalising.",
        "account_details": [
            _acct("Equity", 5_000_000, "SUBMITTED", "NEGLIGIBLE"),
            _acct("KCB", 1_250_000, "MISSING", "MATERIAL"),
        ],
    }
    base.update(over)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Unavailable branch — the ONLY branch the real Deed document exercises
# ─────────────────────────────────────────────────────────────────────────────

def test_unavailable_when_no_audited_financials():
    ctx = _assert_equivalent({})
    assert ctx["available"] is False
    assert ctx["note"] == ACCOUNT_COVERAGE_UNAVAILABLE_NOTE
    assert "Submit audited financials" in ctx["note"]


def test_unavailable_for_skipped_result_which_is_truthy_but_has_no_coverage_pct():
    """
    calculate_account_coverage() returns {"status": "SKIPPED", "reason": ...}
    when the audited financials carry no cash_breakdown. That dict is truthy,
    so branching on dict-emptiness instead of coverage_pct would wrongly take
    the populated path.
    """
    ctx = _assert_equivalent({"status": "SKIPPED", "reason": "No cash_breakdown in audited financials"})
    assert ctx["available"] is False


def test_unavailable_carries_no_value_fields():
    """Decision #1: null + reason, never sentinel values stuffed into fields."""
    ac = _build_account_coverage({}, "KES")
    assert ac.available is False
    assert ac.coverage is None
    assert ac.advisory_tier is None
    assert ac.missing_balance is None
    assert ac.accounts == []
    assert ac.unavailable_note is not None


# ─────────────────────────────────────────────────────────────────────────────
# Populated branch
# ─────────────────────────────────────────────────────────────────────────────

def test_populated_matches_original():
    ctx = _assert_equivalent(_raw())
    assert ctx["available"] is True
    assert ctx["coverage_pct"] == "87.5"
    assert ctx["coverage_color_class"] == "warn"
    assert ctx["accounts"][0]["status_label"] == "✓ Submitted"
    assert ctx["accounts"][1]["status_label"] == "Missing"


@pytest.mark.parametrize("tier,color", [
    ("NEGLIGIBLE", "ok"), ("MINOR", "warn"), ("MATERIAL", "warn"), ("CRITICAL", "critical"),
])
def test_every_advisory_tier_maps_to_original_colour(tier, color):
    ctx = _assert_equivalent(_raw(advisory_tier=tier))
    assert ctx["coverage_color_class"] == color


@pytest.mark.parametrize("materiality,pill", [
    ("NEGLIGIBLE", "status-matched"), ("MINOR", "status-matched"),
    ("MATERIAL", "status-critical"), ("CRITICAL", "status-critical"),
])
def test_every_materiality_maps_to_original_pill(materiality, pill):
    ctx = _assert_equivalent(_raw(account_details=[_acct("Equity", 100, "SUBMITTED", materiality)]))
    assert ctx["accounts"][0]["materiality_class"] == pill


def test_unknown_advisory_tier_falls_back_to_critical_colour():
    ctx = _assert_equivalent(_raw(advisory_tier="SOMETHING_NEW"))
    assert ctx["coverage_color_class"] == "critical"


def test_empty_bank_name_and_materiality_fall_back_to_dashes():
    ctx = _assert_equivalent(_raw(account_details=[_acct("", 0, "MISSING", "")]))
    assert ctx["accounts"][0]["bank_name"] == "--"
    assert ctx["accounts"][0]["materiality"] == "--"
    assert ctx["accounts"][0]["materiality_class"] == "status-critical"


def test_zero_coverage_is_populated_not_unavailable():
    """0.0 is falsy but not None — a real prod deal (Kenlinks) has exactly this."""
    ctx = _assert_equivalent(_raw(coverage_pct=0.0))
    assert ctx["available"] is True
    assert ctx["coverage_pct"] == "0.0"


def test_no_account_details_still_populated():
    ctx = _assert_equivalent(_raw(account_details=[]))
    assert ctx["available"] is True
    assert ctx["accounts"] == []


def test_missing_balance_none_renders_as_zero():
    ctx = _assert_equivalent(_raw(missing_balance_cents=None))
    assert ctx["missing_balance_str"] == "KES 0"


# ─────────────────────────────────────────────────────────────────────────────
# The formatting fix — the real defect this stage found
# ─────────────────────────────────────────────────────────────────────────────

def test_coverage_pct_round_trip_matches_original_for_every_possible_value():
    """
    coverage_pct is produced upstream as round(basis_points / 100, 2), so the
    complete input domain is the 10,001 hundredths from 0.00 to 100.00. The
    context stores a 0-1 fraction (decision #3); formatting it back must
    reproduce the original's f"{value:.1f}" for EVERY one of them.

    The naive `value * 100` round-trip fails 45 of these.
    """
    naive_failures = []
    for bp in range(0, 10001):
        raw_pct = round(bp / 100, 2)
        expected = f"{raw_pct:.1f}"
        assert _fmt_pct_1dp(Percent(value=raw_pct / 100)) == expected, (
            f"coverage_pct={raw_pct} formatted wrongly"
        )
        if f"{raw_pct / 100 * 100:.1f}" != expected:
            naive_failures.append(raw_pct)

    # Guard the guard: if this ever hits zero the test has stopped proving
    # anything and the naive form would pass too.
    assert len(naive_failures) == 45, naive_failures[:10]
    assert 0.85 in naive_failures


def test_risk_assessment_missing_pct_uses_the_same_corrected_formatting():
    """
    Stage 1 regression. The pre-Stage-1 original set the Risk Assessment's
    missing_pct from Account Coverage's already-formatted coverage_pct string,
    so the two must agree exactly.
    """
    for bp in (85, 165, 745, 1295, 8747, 7321, 1426, 0, 10000):
        raw_pct = round(bp / 100, 2)
        risk = RiskAssessment(
            tier="MEDIUM_CONFIDENCE", advisory_tier="MINOR",
            coverage=Percent(value=raw_pct / 100), largest_revenue_share=None,
            revenue_concentration_sample=None, revenue_concentration_state="UNAVAILABLE",
            anomaly_narrative="x", conclusion="c", transfer_caveat="t",
        )
        risk_str = _risk_assessment_ctx_from(risk)["missing_pct"]
        coverage_str = _account_coverage_ctx_from(
            _build_account_coverage(_raw(coverage_pct=raw_pct), "KES")
        )["coverage_pct"]
        assert risk_str == f"{raw_pct:.1f}" == coverage_str


def test_risk_assessment_missing_pct_still_dashes_when_coverage_absent():
    risk = RiskAssessment(
        tier="OBSERVED", advisory_tier=None, coverage=None,
        largest_revenue_share=None, revenue_concentration_sample=None,
        revenue_concentration_state="UNAVAILABLE",
        anomaly_narrative="x", conclusion="c", transfer_caveat="t",
    )
    assert _risk_assessment_ctx_from(risk)["missing_pct"] == "--"


# ─────────────────────────────────────────────────────────────────────────────
# Typed-schema assertions (PAR-189 ratified conventions)
# ─────────────────────────────────────────────────────────────────────────────

def test_coverage_is_a_zero_to_one_fraction():
    ac = _build_account_coverage(_raw(coverage_pct=87.47), "KES")
    assert isinstance(ac.coverage, Percent)
    assert 0.0 <= ac.coverage.value <= 1.0
    assert round(ac.coverage.value, 4) == 0.8747


def test_status_and_materiality_are_semantic_not_css():
    ac = _build_account_coverage(_raw(), "KES")
    assert [a.status for a in ac.accounts] == ["SUBMITTED", "MISSING"]
    assert ac.accounts[0].materiality == "NEGLIGIBLE"


def test_context_carries_no_markup_css_or_glyphs():
    ac = _build_account_coverage(_raw(), "KES")
    blob = repr(ac)
    for forbidden in ("status-matched", "status-missing", "status-critical",
                      "✓", "class=", "<", "#0"):
        assert forbidden not in blob, forbidden


def test_declared_balances_are_typed_money_with_currency():
    ac = _build_account_coverage(_raw(), "USD")
    assert ac.accounts[0].declared_balance == Money(5_000_000, "USD")
    assert ac.missing_balance == Money(1_250_000, "USD")


def test_unavailable_note_is_shared_prose_constant():
    """Decision #2: narrative stays a pre-written prose string."""
    assert isinstance(ACCOUNT_COVERAGE_UNAVAILABLE_NOTE, str)
    assert _build_account_coverage({}, "KES").unavailable_note is ACCOUNT_COVERAGE_UNAVAILABLE_NOTE
