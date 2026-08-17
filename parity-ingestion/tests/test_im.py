"""Tests for I&M Bank (Kenya) PDF extractor.

Fixtures referenced directly from Desktop (real customer statements,
never committed — see ABSA's test for the same convention). If absent,
the file-dependent class is skipped; the pure-helper unit tests below
always run.
"""
from __future__ import annotations

import pathlib

import pytest

from app.extractors.im_extractor import (
    _parse_im_date,
    _try_parse_balance,
    detect_im,
    extract_im_pdf,
)
from app.normaliser import normalise_all

SAMPLES = "/Users/mbakswatu/Desktop/Deedfilesmusa"
IM_PDF_1 = f"{SAMPLES}/Deed Statement Jun 15 2026.pdf"
IM_PDF_2 = f"{SAMPLES}/Deed Statement Jun 15 2026 (1).pdf"


def _can_open(path: str) -> bool:
    if not pathlib.Path(path).exists():
        return False
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            _ = pdf.pages[0].extract_text()
        return True
    except Exception:
        return False


# ── Unit tests (no fixture required) ─────────────────────────────────────────

class TestParseImDateUnit:
    def test_standard(self):
        assert _parse_im_date("02-Mar-2026") == "2026-03-02"

    def test_single_digit_day(self):
        assert _parse_im_date("3-Dec-2025") == "2025-12-03"

    def test_invalid_returns_none(self):
        assert _parse_im_date("not-a-date") is None

    def test_empty_returns_none(self):
        assert _parse_im_date("") is None


class TestTryParseBalanceUnit:
    def test_standard(self):
        cents, warn = _try_parse_balance("18,195.23")
        assert cents == 1819523
        assert warn is None

    def test_no_decimals(self):
        cents, warn = _try_parse_balance("2300")
        assert cents == 230000
        assert warn is None

    def test_empty(self):
        cents, warn = _try_parse_balance("")
        assert cents is None
        assert warn is None

    def test_malformed(self):
        cents, warn = _try_parse_balance("not-a-number")
        assert cents is None
        assert warn is not None


# ── File-dependent tests (skipped if fixtures absent) ────────────────────────

@pytest.mark.skipif(not _can_open(IM_PDF_1), reason="I&M fixture 1 missing or unreadable")
class TestImExtractorFile1:
    def test_detect_im(self):
        assert detect_im(IM_PDF_1) is True

    def test_file_not_rejected(self):
        result = extract_im_pdf(IM_PDF_1)
        assert result.extraction_status in ("success", "needs_review")
        assert len(result.raw_transactions) > 0

    def test_no_floats(self):
        result = extract_im_pdf(IM_PDF_1)
        normalise_all(result)
        for t in result.normalised_transactions:
            if t.debit_cents is not None:
                assert isinstance(t.debit_cents, int)
            if t.credit_cents is not None:
                assert isinstance(t.credit_cents, int)
            if t.balance_cents is not None:
                assert isinstance(t.balance_cents, int)

    def test_balance_continuity(self):
        """
        Strongest accuracy signal available without separate ground truth:
        for every consecutive pair, prev_balance - debit + credit == balance.
        Confirmed 0 mismatches across 1345 consecutive pairs on this file
        during manual verification.
        """
        result = extract_im_pdf(IM_PDF_1)
        prev_bal = None
        mismatches = 0
        checked = 0
        for t in result.raw_transactions:
            bal, _ = _try_parse_balance(t.balance_raw)
            debit, _ = _try_parse_balance(t.debit_raw)
            credit, _ = _try_parse_balance(t.credit_raw)
            debit = debit or 0
            credit = credit or 0
            if prev_bal is not None and bal is not None:
                checked += 1
                if prev_bal - debit + credit != bal:
                    mismatches += 1
            if bal is not None:
                prev_bal = bal
        assert checked > 0
        assert mismatches == 0

    def test_no_bare_date_only_rows(self):
        """Statement-period boilerplate ("From / 01-Mar-2026") must not be
        captured as a transaction — every real row has a description."""
        result = extract_im_pdf(IM_PDF_1)
        for t in result.raw_transactions:
            assert t.description.strip() != ""


@pytest.mark.skipif(not _can_open(IM_PDF_2), reason="I&M fixture 2 missing or unreadable")
class TestImExtractorFile2:
    def test_detect_im(self):
        assert detect_im(IM_PDF_2) is True

    def test_file_not_rejected(self):
        result = extract_im_pdf(IM_PDF_2)
        assert result.extraction_status in ("success", "needs_review")
        assert len(result.raw_transactions) > 0

    def test_balance_continuity(self):
        result = extract_im_pdf(IM_PDF_2)
        prev_bal = None
        mismatches = 0
        checked = 0
        for t in result.raw_transactions:
            bal, _ = _try_parse_balance(t.balance_raw)
            debit, _ = _try_parse_balance(t.debit_raw)
            credit, _ = _try_parse_balance(t.credit_raw)
            debit = debit or 0
            credit = credit or 0
            if prev_bal is not None and bal is not None:
                checked += 1
                if prev_bal - debit + credit != bal:
                    mismatches += 1
            if bal is not None:
                prev_bal = bal
        assert checked > 0
        assert mismatches == 0


@pytest.mark.skipif(
    not (_can_open(IM_PDF_1) and _can_open(IM_PDF_2)),
    reason="Both I&M fixtures required for cross-file continuity check",
)
def test_cross_file_balance_continuity():
    """
    The two files are sequential statements for the same account
    (Dec 2025-Feb 2026, then Mar-May 2026). The closing balance of the
    earlier file must equal the implied opening balance of the later one.
    """
    earlier = extract_im_pdf(IM_PDF_2)
    later = extract_im_pdf(IM_PDF_1)

    last_bal, _ = _try_parse_balance(earlier.raw_transactions[-1].balance_raw)

    first = later.raw_transactions[0]
    first_bal, _ = _try_parse_balance(first.balance_raw)
    first_debit, _ = _try_parse_balance(first.debit_raw)
    first_credit, _ = _try_parse_balance(first.credit_raw)
    implied_opening = first_bal - (first_credit or 0) + (first_debit or 0)

    assert last_bal == implied_opening
