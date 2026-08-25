"""
PAR-189 — Loan Activity variance-format bug fix (found during Stage 11 review,
in already-merged Stage 4 code, PR #164).

Not a new stage. `_loan_activity_ctx_from()`'s `loan_variance_str` read
`loans.variance` (a 0-1 Percent) with a naive `f"{loans.variance.value * 100:.1f}%"`
instead of `_fmt_pct_1dp()`. `loans.variance` is built in
`_build_loan_activity()` from `loans_r.get("variance_pct")`, which is
`recon_section["loan_activity"]["variance_pct"]` — confirmed by reading
`reconciliation_engine.py` directly: `round(variance_cents /
declared_net_borrowing_cents * 100, 2)`. This is the exact same pre-rounded-
to-hundredths field 4-Point Reconciliation's own loan row already reads
(fixed correctly in Stage 9) — Stage 9 fixed one consumer of this field and
missed this other one.

Existing test_par189_stage4_extraction.py's equivalence tests did not catch
this: its own `_original_loan_ctx()` reference formats the raw (already
2-decimal-rounded) float directly, and none of its SCENARIOS fixture values
happen to land on a float that diverges under the naive round-trip — the
exact "escaped N stages of byte-diffs" pattern Stage 8 first found. This
file adds the specific case that does diverge.

Real-data check (not assumed): computed loan_activity variance_pct directly
via the real reconciliation_engine.py formula against 9 real prod deals with
audited financials (SQL replica of the exact formula, cross-checked against
the source). Real values ranged -143.29% to -236.71%. NONE of the 9 sampled
real values land on a divergent input (748/100,001 across -500%..+500%,
same count as Stage 9's reconciliation variances) — so this is a confirmed
LATENT defect, live on `paritystaging` since Stage 4 (PR #164) merged, not
an observed live misreport on any real deal checked so far. Not yet
promoted to main/prod (per PAR-189's standing note that none of this
extraction has been promoted).
"""
from __future__ import annotations

from v1.analysis.snapshot_context import LoanActivity, Money, Percent
from v1.analysis.snapshot_html_renderer import _fmt_pct_1dp, _loan_activity_ctx_from


def _loans_with_variance(variance_pct) -> LoanActivity:
    return LoanActivity(
        disbursed=Money(cents=0),
        repaid=Money(cents=0),
        net=Money(cents=0),
        repayments_per_month=0.0,
        repayment_txn_count=0,
        facilities=[],
        bank_net=Money(cents=0),
        declared_net=Money(cents=0),
        variance=Percent(value=variance_pct / 100) if variance_pct is not None else None,
        status_raw=None,
    )


def test_loan_variance_str_uses_fmt_pct_1dp_not_naive_multiply():
    # -177.73 is a real value found on a real prod deal (8a16649b) -- does
    # not itself diverge, included as a real-world sanity anchor.
    ctx = _loan_activity_ctx_from(_loans_with_variance(-177.73))
    assert ctx["loan_variance_str"] == "-177.7%"


def test_loan_variance_str_diverges_under_naive_round_trip_but_not_after_fix():
    # -499.95 is one of the 748 confirmed-divergent inputs over -500..+500:
    # naive f"{(-499.95/100)*100:.1f}" == "-500.0" (float error), while the
    # correct re-rounded value is "-499.9". This is the exact digit-shift
    # class of bug Stage 8 found and Stage 9 generalised -- pinned here so a
    # regression back to the naive form fails loud.
    naive = f"{(-499.95 / 100) * 100:.1f}%"
    assert naive == "-500.0%"  # confirms the naive form really is wrong first

    ctx = _loan_activity_ctx_from(_loans_with_variance(-499.95))
    assert ctx["loan_variance_str"] == "-499.9%"
    assert ctx["loan_variance_str"] != naive


def test_loan_variance_str_none_falls_back_to_zero_pct_unchanged():
    ctx = _loan_activity_ctx_from(_loans_with_variance(None))
    assert ctx["loan_variance_str"] == "0%"


def test_full_domain_divergence_count_matches_stage9_reconciliation_variances():
    # Same measurement methodology as Stage 9's report: round(i/100, 2) for
    # i spanning -500.00..500.00 in 0.01 steps -- the range real prod values
    # (-143.29..-236.71, measured this session) sit comfortably inside.
    mismatches = 0
    for i in range(-50000, 50001):
        raw = round(i / 100, 2)
        naive = f"{(raw / 100) * 100:.1f}"
        fixed = _fmt_pct_1dp(Percent(value=raw / 100))
        if naive != fixed:
            mismatches += 1
    assert mismatches == 748


def test_real_prod_loan_variance_values_do_not_hit_the_divergent_set():
    # Measured this session via a SQL replica of reconciliation_engine.py's
    # exact loan_activity variance_pct formula against 9 real prod deals
    # with audited financials. None diverge -- this is a latent defect, not
    # a confirmed live misreport, on the deals checked so far.
    real_values = [-154.11, -236.71, -197.67, -197.70, -177.73, -158.98, -143.29]
    for v in real_values:
        naive = f"{(v / 100) * 100:.1f}"
        fixed = _fmt_pct_1dp(Percent(value=v / 100))
        assert naive == fixed, f"{v} unexpectedly diverges"
