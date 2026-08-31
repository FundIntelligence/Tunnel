"""
PAR-209 — Loan Activity reconciliation sign-flip investigation.

Root cause on the real Buildex deal (deal_id=4f4f4cba-d688-4b9c-a887-71a0dd6b83d5,
FY2025) is NOT classifier under-tagging: an exhaustive keyword sweep (loan,
facility, disburs*, and every named lender in `_LOAN_KEYWORDS` /
`_LOAN_REPAYMENT_PATTERNS`) over every positive-amount fiscal-year transaction
found no missed disbursement-side transactions. The 24 real loan_repayment
transactions (Tendepay, Jiinue) are correctly tagged; the classifier is doing
its job.

The real cause is a structural scope mismatch, confirmed two ways:

1. `pds_audited_financials.loan_breakdown` for this deal shows the loan
   portfolio is dominated by 3 "AssetFinance-*" facilities (KES 14.03M of
   KES 20.33M total loan balance). Asset-finance disbursements are paid
   directly to the equipment vendor, never crediting the borrower's own bank
   account — there is no bank-observable credit for the classifier to ever
   tag, regardless of keyword coverage. This is a definitional gap between
   "audited financing cashflow" (whole-company, includes non-cash-to-borrower
   drawdowns) and "bank-visible loan roles" (only sees cash that actually hit
   an ingested account) — not something a keyword fix can close, and not
   something to encode as a new classifier rule without Parity Science
   sign-off per PAR-150 (loan_breakdown "name" values are free-text, not a
   controlled vocabulary).

2. Compounding this for Buildex specifically: `pds_account_coverage` shows the
   deal has 4 declared bank accounts (KCB, Absa, Zemo, Equity) but only 2
   (KCB, Equity) were ever submitted. `account_coverage_advisory` is already
   persisted as MATERIAL (87.47% coverage) on `pds_audited_financials` for
   this deal — the system already knows about this gap and uses it to gate
   the HIGH_CONFIDENCE tier (see `snapshot_generator._compute_tier`), but
   `calculate_loan_activity_reconciliation()` never referenced it, so a known
   data-coverage gap silently produced what looked like a wild, sign-flipped
   formula bug on this one row.

PAR-189's own real-data check (test_par189_stage4_loan_variance_fmt_fix.py)
found loan_activity variance_pct on 9 real prod deals all falling in
-143%..-237% — every deal with loan activity shows the same large,
sign-disagreeing pattern. That uniformity is more consistent with a
structural/definitional gap (declared financing includes bank-invisible
asset-finance drawdowns, on every deal) than a per-deal classifier miss,
which would be expected to vary in sign and magnitude deal to deal.

No classifier.py change: nothing here is a malformed keyword or a scope bug
in an approved rule — see Boundary note in the PAR-209 ticket. The fix in
this file is a reconciliation_engine.py behavior change: attach the deal's
already-computed account_coverage advisory to a VARIANCE loan_activity result
so consumers can distinguish "known data gap" from "formula defect" rather
than force a code fix that papers over the asset-finance definitional gap
(that part is flagged back to PAR-209 as a scoping question, not fixed here).
"""
import os
import sys

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import backend.v1.analysis.reconciliation_engine as re_engine


def _af(**overrides):
    af = {
        "financial_year_start": "2025-01-01",
        "financial_year_end": "2025-12-31",
        "financing_cashflow_cents": 255_709_200,  # KES 2,557,092.00 (Buildex FY2025)
    }
    af.update(overrides)
    return af


def _txns():
    # Reproduces Buildex FY2025: KES 31,000 disbursed (1 txn) vs
    # KES 3,526,696 repaid (24 txns) -> bank_net_borrowing = -3,495,696 KES,
    # variance_pct = -236.7% against the declared +2,557,092 KES.
    rows = [{"signed_amount_cents": 3_100_000, "role": "loan_inflow"}]
    rows += [{"signed_amount_cents": -146_945_667, "role": "loan_repayment"}]
    return rows


def test_variance_carries_material_coverage_note_when_accounts_missing(monkeypatch):
    monkeypatch.setattr(re_engine, "_get_audited_financials", lambda deal_id: _af())
    monkeypatch.setattr(
        re_engine, "_get_fiscal_year_transactions", lambda deal_id, s, e: _txns()
    )
    monkeypatch.setattr(
        re_engine,
        "calculate_account_coverage",
        lambda deal_id: {
            "coverage_pct": 87.47,
            "advisory_tier": "MATERIAL",
            "missing_accounts_count": 2,
        },
    )

    result = re_engine.calculate_loan_activity_reconciliation("buildex-deal")

    assert result["status"] == "VARIANCE"
    assert result["account_coverage_note"] is not None
    assert "MATERIAL" in result["account_coverage_note"]
    assert "2 missing" in result["account_coverage_note"]


def test_variance_has_no_coverage_note_when_coverage_is_full(monkeypatch):
    monkeypatch.setattr(re_engine, "_get_audited_financials", lambda deal_id: _af())
    monkeypatch.setattr(
        re_engine, "_get_fiscal_year_transactions", lambda deal_id, s, e: _txns()
    )
    monkeypatch.setattr(
        re_engine,
        "calculate_account_coverage",
        lambda deal_id: {
            "coverage_pct": 100.0,
            "advisory_tier": "NEGLIGIBLE",
            "missing_accounts_count": 0,
        },
    )

    result = re_engine.calculate_loan_activity_reconciliation("fully-covered-deal")

    assert result["status"] == "VARIANCE"
    assert result["account_coverage_note"] is None


def test_exact_match_never_carries_a_coverage_note_even_if_accounts_missing(monkeypatch):
    # A coverage gap is irrelevant noise once the reconciliation already
    # matches — don't attach a caveat that isn't explaining anything.
    monkeypatch.setattr(
        re_engine,
        "_get_audited_financials",
        lambda deal_id: _af(financing_cashflow_cents=3_100_000 - 146_945_667),
    )
    monkeypatch.setattr(
        re_engine, "_get_fiscal_year_transactions", lambda deal_id, s, e: _txns()
    )
    monkeypatch.setattr(
        re_engine,
        "calculate_account_coverage",
        lambda deal_id: {
            "coverage_pct": 14.26,
            "advisory_tier": "CRITICAL",
            "missing_accounts_count": 3,
        },
    )

    result = re_engine.calculate_loan_activity_reconciliation("exact-match-deal")

    assert result["status"] == "EXACT_MATCH"
    assert result["account_coverage_note"] is None


def test_coverage_lookup_failure_does_not_break_loan_reconciliation(monkeypatch):
    # account_coverage has its own failure modes (e.g. missing cash_breakdown
    # returns {"status": "SKIPPED", ...} with no "advisory_tier" key at all).
    # The loan row must degrade to no-caveat, not raise.
    monkeypatch.setattr(re_engine, "_get_audited_financials", lambda deal_id: _af())
    monkeypatch.setattr(
        re_engine, "_get_fiscal_year_transactions", lambda deal_id, s, e: _txns()
    )

    def _raises(deal_id):
        raise ValueError("No cash_breakdown in audited financials")

    monkeypatch.setattr(re_engine, "calculate_account_coverage", _raises)

    result = re_engine.calculate_loan_activity_reconciliation("no-coverage-data-deal")

    assert result["status"] == "VARIANCE"
    assert result["account_coverage_note"] is None
