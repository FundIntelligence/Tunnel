"""
PAR-189 Stage 9 verification — 4-Point Reconciliation extraction into
build_snapshot_context().

Same pattern as Stages 1-8: the real acceptance bar is a full-document
byte-diff of render_snapshot_html()'s output on the real Deed document (run
separately; PASS, byte-identical, reported on PAR-189).

Deed has no audited financials, so recon_available is False and NONE of the
four rows render there — the byte-diff proves only that the unavailable path
is inert. Per the Stage 8 lesson, the populated branch was verified
separately by driving the REAL generate_reconciliation_section() over real
prod deals that do have audited financials (2 deals, all four rows, 0
mismatches — see the Stage 9 report). These fixtures cover the branch matrix
that real data happens not to reach.
"""
from __future__ import annotations

import pytest

from v1.analysis.snapshot_context import (
    DEFAULT_RECON_CHECK_CONFIG,
    FourPointReconciliation,
    Money,
    Percent,
    ReconCheckConfig,
    _build_four_point_reconciliation,
)
from v1.analysis.snapshot_html_renderer import (
    _BADGE_VARIANCE_CLASS,
    _fmt_pct_1dp,
    _four_point_recon_ctx_from,
    _status_to_badge,
)


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-9 source
# (snapshot_html_renderer.py as merged at d90bf10).
# ─────────────────────────────────────────────────────────────────────────────

def _original(recon_section, recon_available, acct_cov_raw, fy):
    recon_rows = []
    recon_fiscal_note = ""
    missing_bank_names = [
        a.get("bank_name") for a in (acct_cov_raw.get("account_details") or [])
        if a.get("status") != "SUBMITTED" and a.get("bank_name")
    ]
    coverage_incomplete = recon_available and bool(missing_bank_names)
    missing_note = (
        f"Coverage gap — {', '.join(missing_bank_names)} not submitted."
        if coverage_incomplete else ""
    )
    if recon_available:
        cash_r = recon_section.get("cash_position") or {}
        rev_r = recon_section.get("revenue") or {}
        exp_r = recon_section.get("expenses") or {}
        loan_r = recon_section.get("loan_activity") or {}

        fp = rev_r.get("fiscal_period") or ""
        if " to " in fp:
            recon_fiscal_note = f"All checks at fiscal year-end {fp.split(' to ')[-1]}"
        elif fy:
            recon_fiscal_note = f"All checks at fiscal year-end Dec 31 {fy}"

        cash_var = cash_r.get("variance_pct")
        cash_status = cash_r.get("status") or "SKIPPED"
        cash_badge = _status_to_badge(cash_status)          # NOTE: no coverage arg
        if cash_status == "EXACT_MATCH":
            cash_assessment = "On submitted accounts: KES 0 variance."
        elif cash_var is not None:
            cash_assessment = f"{abs(cash_var):.1f}% variance on submitted accounts."
        else:
            cash_assessment = cash_r.get("reason") or "Insufficient data."
        recon_rows.append({
            "check": "Cash position",
            "observed_str": _fmt_kes(int(cash_r.get("total_bank_kes", 0) * 100)),
            "observed_sub": "Bank accounts at fiscal year-end",
            "declared_str": _fmt_kes(int(cash_r.get("total_declared_kes", 0) * 100)),
            "declared_sub": "Note 11 · cash and equivalents",
            "variance_str": f"{cash_var:.1f}%" if cash_var is not None else "--",
            "variance_class": _BADGE_VARIANCE_CLASS[cash_badge[0]],
            "badge_class": cash_badge[0],
            "badge_label": cash_badge[1],
            "assessment": cash_assessment,
        })

        rev_gap = rev_r.get("gap_pct")
        rev_text = rev_r.get("assessment") or ""
        rev_status = (
            "HEALTHY" if "HEALTHY" in rev_text
            else ("ACCEPTABLE" if "WARNING" not in rev_text and "RISK" not in rev_text else "VARIANCE")
        )
        rev_badge = _status_to_badge(rev_status, coverage_incomplete)
        rev_assessment = rev_text or "--"
        if rev_badge[0] == "b-warn":
            rev_assessment = f"{rev_assessment.rstrip('.')} {missing_note}"
        recon_rows.append({
            "check": "Revenue",
            "observed_str": _fmt_kes(int(rev_r.get("bank_inflows_kes", 0) * 100)),
            "observed_sub": "Net operational inflows",
            "declared_str": _fmt_kes(int(rev_r.get("declared_revenue_kes", 0) * 100)),
            "declared_sub": "Declared turnover",
            "variance_str": f"{rev_gap:.1f}% gap" if rev_gap is not None else "--",
            "variance_class": _BADGE_VARIANCE_CLASS[rev_badge[0]],
            "badge_class": rev_badge[0],
            "badge_label": rev_badge[1],
            "assessment": rev_assessment,
        })

        exp_gap = exp_r.get("gap_pct")
        exp_badge = _status_to_badge(
            "ACCEPTABLE" if abs(exp_gap or 0) <= 15 else "VARIANCE", coverage_incomplete)
        exp_assessment = exp_r.get("explanation") or "--"
        if exp_badge[0] == "b-warn":
            exp_assessment = f"{exp_assessment.rstrip('.')} {missing_note}"
        recon_rows.append({
            "check": "Expenses",
            "observed_str": _fmt_kes(int(exp_r.get("bank_outflows_kes", 0) * 100)),
            "observed_sub": "Net operational outflows",
            "declared_str": _fmt_kes(int(exp_r.get("declared_expenses_kes", 0) * 100)),
            "declared_sub": "Total declared expenses",
            "variance_str": f"{exp_gap:.1f}% gap" if exp_gap is not None else "--",
            "variance_class": _BADGE_VARIANCE_CLASS[exp_badge[0]],
            "badge_class": exp_badge[0],
            "badge_label": exp_badge[1],
            "assessment": exp_assessment,
        })

        loan_var = loan_r.get("variance_pct")
        loan_status = loan_r.get("status") or "VARIANCE"
        loan_badge = _status_to_badge(loan_status, coverage_incomplete)
        if loan_status == "EXACT_MATCH":
            loan_assessment = "Net borrowing matches cashflow statement exactly."
        elif loan_var is not None:
            loan_assessment = f"{abs(loan_var):.1f}% variance — review facility discrepancy."
        else:
            loan_assessment = loan_r.get("reason") or "Insufficient data."
        if loan_badge[0] == "b-warn":
            loan_assessment = f"{loan_assessment.rstrip('.')} {missing_note}"
        recon_rows.append({
            "check": "Loan activity",
            "observed_str": _fmt_kes(int(loan_r.get("bank_net_borrowing_kes", 0) * 100)),
            "observed_sub": "Net borrowings · bank-detected",
            "declared_str": _fmt_kes(int(loan_r.get("declared_net_borrowing_kes", 0) * 100)),
            "declared_sub": "Cashflow statement · Note 14",
            "variance_str": f"{loan_var:.1f}%" if loan_var is not None else "0%",
            "variance_class": _BADGE_VARIANCE_CLASS[loan_badge[0]],
            "badge_class": loan_badge[0],
            "badge_label": loan_badge[1],
            "assessment": loan_assessment,
        })
    return {"recon_rows": recon_rows, "recon_fiscal_note": recon_fiscal_note}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _section(**over):
    base = {
        "cash_position": {
            "status": "ACCEPTABLE", "variance_pct": -44.3,
            "total_bank_kes": 11834.94, "total_declared_kes": 21257.81,
        },
        "revenue": {
            "gap_pct": 91.4, "assessment": "RISK — revenue gap too large (>15%)",
            "fiscal_period": "2025-01-01 to 2025-12-31",
            "bank_inflows_kes": 319000.56, "declared_revenue_kes": 3720622.77,
        },
        "expenses": {
            "gap_pct": 90.4, "explanation": "Gap explained by: non-cash expenses.",
            "bank_outflows_kes": 350533.17, "declared_expenses_kes": 3637320.91,
        },
        "loan_activity": {
            "status": "VARIANCE", "variance_pct": -177.7,
            "bank_net_borrowing_kes": -19875.34, "declared_net_borrowing_kes": 25570.92,
        },
    }
    for k, v in over.items():
        if v is None:
            base.pop(k, None)
        elif isinstance(v, dict) and k in base:
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def _cov(*missing):
    return {"account_details": [
        {"bank_name": b, "status": "MISSING"} for b in missing
    ] + [{"bank_name": "Equity", "status": "SUBMITTED"}]}


def _assert_equiv(section, acct_cov_raw=None, fy="2025", available=True):
    acct_cov_raw = acct_cov_raw or {}
    missing = [
        a.get("bank_name") for a in (acct_cov_raw.get("account_details") or [])
        if a.get("status") != "SUBMITTED" and a.get("bank_name")
    ]
    coverage_incomplete = available and bool(missing)
    missing_note = (
        f"Coverage gap — {', '.join(missing)} not submitted." if coverage_incomplete else ""
    )
    original = _original(section, available, acct_cov_raw, fy)
    new = _four_point_recon_ctx_from(
        _build_four_point_reconciliation(
            section, available, coverage_incomplete, missing_note, fy, "KES")
    )
    assert new == original
    return new


# ─────────────────────────────────────────────────────────────────────────────
# Unavailable branch — what the real Deed document renders
# ─────────────────────────────────────────────────────────────────────────────

def test_unavailable_yields_no_rows_and_empty_fiscal_note():
    ctx = _assert_equiv({}, available=False)
    assert ctx["recon_rows"] == []
    assert ctx["recon_fiscal_note"] == ""


def test_unavailable_dataclass_carries_nulls_not_sentinels():
    fpr = _build_four_point_reconciliation({}, False, False, "", "2025", "KES")
    assert fpr.available is False
    assert fpr.checks == []
    assert fpr.fiscal_note is None


# ─────────────────────────────────────────────────────────────────────────────
# Fidelity point 1 — cash position is NEVER coverage-softened
# ─────────────────────────────────────────────────────────────────────────────

def test_cash_is_not_coverage_softened_while_other_rows_are():
    """
    The single most important behaviour in this section. With coverage
    incomplete, revenue/expenses/loan soften to b-warn but cash must stay
    b-variance — the declared Note 11 balance is the company's own
    attestation, so a variance there is unexplained regardless of which
    statements are missing. Observed on real prod data too (Stage 9 report).
    """
    ctx = _assert_equiv(_section(cash_position={"status": "VARIANCE"}), _cov("Absa", "Zemo"))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Cash position"]["badge_class"] == "b-variance"
    assert rows["Revenue"]["badge_class"] == "b-warn"
    assert rows["Expenses"]["badge_class"] == "b-warn"
    assert rows["Loan activity"]["badge_class"] == "b-warn"


def test_cash_assessment_never_gets_missing_note_appended():
    ctx = _assert_equiv(_section(cash_position={"status": "VARIANCE"}), _cov("Absa"))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert "Coverage gap" not in rows["Cash position"]["assessment"]
    assert "Coverage gap — Absa not submitted." in rows["Revenue"]["assessment"]


# ─────────────────────────────────────────────────────────────────────────────
# Fidelity point 2 — each row derives status differently
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("HEALTHY — within tolerance", "b-ok"),
    ("Everything nominal", "b-ok"),                 # no WARNING/RISK -> ACCEPTABLE
    ("WARNING — gap widening", "b-variance"),
    ("RISK — revenue gap too large (>15%)", "b-variance"),
    ("", "b-ok"),                                   # empty -> ACCEPTABLE
])
def test_revenue_status_is_parsed_from_free_text(text, expected):
    ctx = _assert_equiv(_section(revenue={"assessment": text}))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Revenue"]["badge_class"] == expected


def test_revenue_healthy_wins_even_when_risk_also_present():
    """"HEALTHY" is checked first, so a string containing both resolves ok."""
    ctx = _assert_equiv(_section(revenue={"assessment": "HEALTHY but RISK noted"}))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Revenue"]["badge_class"] == "b-ok"


@pytest.mark.parametrize("gap,expected", [
    (0, "b-ok"), (15, "b-ok"), (-15, "b-ok"),        # boundary is inclusive, on abs()
    (15.01, "b-variance"), (-15.01, "b-variance"), (90.4, "b-variance"),
    (None, "b-ok"),                                  # None -> abs(0) -> ACCEPTABLE
])
def test_expense_status_is_purely_gap_magnitude(gap, expected):
    ctx = _assert_equiv(_section(expenses={"gap_pct": gap}))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Expenses"]["badge_class"] == expected


def test_expense_status_ignores_the_subdicts_own_status_field():
    """The original never reads expenses.status — only the gap magnitude."""
    ctx = _assert_equiv(_section(expenses={"gap_pct": 1.0, "status": "VARIANCE"}))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Expenses"]["badge_class"] == "b-ok"


def test_expense_threshold_is_named_config_not_hardcoded():
    """Decision #4: threshold carried as config, value unchanged from original."""
    assert DEFAULT_RECON_CHECK_CONFIG.expense_acceptable_gap_pct == 15.0
    tight = ReconCheckConfig(expense_acceptable_gap_pct=5.0)
    fpr = _build_four_point_reconciliation(
        _section(expenses={"gap_pct": 10.0}), True, False, "", "2025", "KES", tight)
    exp = [c for c in fpr.checks if c.key == "expenses"][0]
    assert exp.status == "VARIANCE"          # 10 > 5 under the tightened config


def test_loan_status_defaults_to_variance_when_absent():
    ctx = _assert_equiv(_section(loan_activity={"status": None}))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Loan activity"]["badge_class"] == "b-variance"


@pytest.mark.parametrize("status", ["EXACT_MATCH", "ACCEPTABLE", "ACCEPTABLE_VARIANCE", "HEALTHY"])
def test_loan_and_cash_accept_all_original_status_synonyms(status):
    ctx = _assert_equiv(_section(
        cash_position={"status": status}, loan_activity={"status": status}))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Cash position"]["badge_class"] in ("b-exact", "b-ok")
    assert rows["Loan activity"]["badge_class"] in ("b-exact", "b-ok")


# ─────────────────────────────────────────────────────────────────────────────
# Per-row variance formatting — suffixes and fallbacks differ
# ─────────────────────────────────────────────────────────────────────────────

def test_variance_suffixes_and_fallbacks_are_per_row():
    ctx = _assert_equiv(_section(
        cash_position={"variance_pct": None},
        revenue={"gap_pct": None},
        expenses={"gap_pct": None},
        loan_activity={"variance_pct": None},
    ))
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Cash position"]["variance_str"] == "--"
    assert rows["Revenue"]["variance_str"] == "--"
    assert rows["Expenses"]["variance_str"] == "--"
    assert rows["Loan activity"]["variance_str"] == "0%"      # the odd one out


def test_variance_suffix_gap_only_on_revenue_and_expenses():
    ctx = _assert_equiv(_section())
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Revenue"]["variance_str"].endswith("% gap")
    assert rows["Expenses"]["variance_str"].endswith("% gap")
    assert rows["Cash position"]["variance_str"] == "-44.3%"
    assert rows["Loan activity"]["variance_str"] == "-177.7%"


def test_negative_variance_uses_abs_in_assessment_but_signed_in_column():
    ctx = _assert_equiv(_section())
    rows = {r["check"]: r for r in ctx["recon_rows"]}
    assert rows["Loan activity"]["variance_str"] == "-177.7%"
    assert "177.7% variance — review facility discrepancy" in rows["Loan activity"]["assessment"]
    assert "-177.7% variance" not in rows["Loan activity"]["assessment"]


# ─────────────────────────────────────────────────────────────────────────────
# The percent round-trip — same class of bug Stage 8 found, wider domain
# ─────────────────────────────────────────────────────────────────────────────

def test_percent_round_trip_holds_across_negative_and_large_values():
    """
    Reconciliation variances are round(x, 2) hundredths like coverage_pct, but
    unlike coverage they are unbounded and frequently negative (a real prod
    deal shows -177.7%). Naive `value * 100` formatting diverges on 748 of the
    100,001 values in -500%..+500%; the re-round in _fmt_pct_1dp fixes all.
    """
    naive_failures = 0
    for h in range(-50000, 50001):
        raw = round(h / 100, 2)
        expected = f"{raw:.1f}"
        assert _fmt_pct_1dp(Percent(raw / 100)) == expected, raw
        if f"{raw / 100 * 100:.1f}" != expected:
            naive_failures += 1
    assert naive_failures == 748, naive_failures


# ─────────────────────────────────────────────────────────────────────────────
# Money conversion + fiscal note
# ─────────────────────────────────────────────────────────────────────────────

def test_kes_float_to_cents_truncates_like_the_original():
    """int(x * 100) truncates toward zero; round() would shift half-cents."""
    fpr = _build_four_point_reconciliation(
        _section(cash_position={"total_bank_kes": 100.999, "total_declared_kes": -100.999}),
        True, False, "", "2025", "KES")
    cash = [c for c in fpr.checks if c.key == "cash_position"][0]
    assert cash.observed == Money(10099, "KES")
    assert cash.declared == Money(-10099, "KES")


def test_fiscal_note_prefers_fiscal_period_over_financial_year():
    ctx = _assert_equiv(_section(), fy="2025")
    assert ctx["recon_fiscal_note"] == "All checks at fiscal year-end 2025-12-31"


def test_fiscal_note_falls_back_to_financial_year():
    ctx = _assert_equiv(_section(revenue={"fiscal_period": ""}), fy="2024")
    assert ctx["recon_fiscal_note"] == "All checks at fiscal year-end Dec 31 2024"


def test_fiscal_note_empty_when_neither_available():
    ctx = _assert_equiv(_section(revenue={"fiscal_period": ""}), fy="")
    assert ctx["recon_fiscal_note"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# Typed-schema assertions
# ─────────────────────────────────────────────────────────────────────────────

def test_context_carries_no_css_classes_or_badge_labels():
    fpr = _build_four_point_reconciliation(_section(), True, True, "note", "2025", "KES")
    blob = repr(fpr)
    for forbidden in ("b-exact", "b-ok", "b-warn", "b-variance", "Exact match",
                      "Acceptable", "Variance", "class=", "<"):
        assert forbidden not in blob, forbidden


def test_checks_carry_semantic_status_and_typed_money():
    fpr = _build_four_point_reconciliation(_section(), True, False, "", "2025", "KES")
    assert [c.key for c in fpr.checks] == [
        "cash_position", "revenue", "expenses", "loan_activity"]
    for c in fpr.checks:
        assert c.status in ("EXACT_MATCH", "ACCEPTABLE", "COVERAGE_GAP", "VARIANCE")
        assert isinstance(c.observed, Money) and isinstance(c.declared, Money)
        assert c.variance is None or isinstance(c.variance, Percent)


def test_coverage_gap_status_only_appears_when_coverage_incomplete():
    without = _build_four_point_reconciliation(_section(), True, False, "", "2025", "KES")
    assert all(c.status != "COVERAGE_GAP" for c in without.checks)
    with_gap = _build_four_point_reconciliation(
        _section(cash_position={"status": "VARIANCE"}), True, True, "n", "2025", "KES")
    assert [c.status for c in with_gap.checks if c.key == "cash_position"] == ["VARIANCE"]
    assert any(c.status == "COVERAGE_GAP" for c in with_gap.checks if c.key != "cash_position")
