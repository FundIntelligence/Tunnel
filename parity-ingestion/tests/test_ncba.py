"""Tests for NCBA Bank Kenya PDF extractor.

Fixture referenced directly from Desktop (real customer statement, never
committed — same convention as test_absa.py / test_im.py). Skipped
gracefully if absent.

Covers the ruled-table template (Posting Date | Value Date | Bank Reference
| Channel Reference | Transaction Type | Transaction Details | Debit Amount
| Credit Amount | Running Balance) added in this fix: the brand renders as
a logo image only on this template (never in extract_text(), no identifying
PDF metadata), and extract_text() itself produces garbled, wrapped-mid-word
output that the original regex line parser can't read — but extract_tables()
returns clean columned rows directly, since this PDF (unlike Absa/I&M) has
real ruled borders.
"""
from __future__ import annotations

import pathlib

import pytest

from app.extractors.ncba_extractor import (
    _parse_ncba_date,
    detect_ncba,
    extract_ncba_pdf,
)

SAMPLES = "/Users/mbakswatu/Desktop/Deedfilesmusa"
NCBA_PDF = f"{SAMPLES}/Account Statement TBC June 15.pdf"


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


def _to_cents(raw: str) -> int:
    if not raw:
        return 0
    clean = raw.replace(",", "").strip()
    if "." in clean:
        whole, frac = clean.split(".", 1)
        frac = (frac + "00")[:2]
        return int(whole or 0) * 100 + int(frac)
    return int(clean) * 100


# ── Unit tests (no fixture required) ─────────────────────────────────────────

class TestParseNcbaDateUnit:
    def test_ddmmyyyy_slash(self):
        assert _parse_ncba_date("04/12/2025") == "2025-12-04"

    def test_ddmmyyyy_dash(self):
        assert _parse_ncba_date("04-12-2025") == "2025-12-04"

    def test_ddmonyyyy(self):
        assert _parse_ncba_date("20 JUL 2023") == "2023-07-20"

    def test_invalid_returns_none(self):
        assert _parse_ncba_date("not-a-date") is None


# ── File-dependent tests (skipped if fixture absent) ────────────────────────

@pytest.mark.skipif(not _can_open(NCBA_PDF), reason="NCBA fixture missing or unreadable")
class TestNcbaRuledTableTemplate:
    def test_detect_ncba(self):
        assert detect_ncba(NCBA_PDF) is True

    def test_file_not_rejected(self):
        result = extract_ncba_pdf(NCBA_PDF)
        assert result.extraction_status == "success"
        assert len(result.raw_transactions) > 0
        assert result.extractor_type == "ncba_pdf"

    def test_totals_match_statement_declared_figures(self):
        """Strongest available accuracy signal: this statement declares its
        own Total Credits / Total Debits in the account header — sum of
        extracted credits/debits must match exactly."""
        result = extract_ncba_pdf(NCBA_PDF)
        total_debit = sum(_to_cents(t.debit_raw) for t in result.raw_transactions)
        total_credit = sum(_to_cents(t.credit_raw) for t in result.raw_transactions)
        assert total_debit == 1121443625   # KES 11,214,436.25
        assert total_credit == 1126924600  # KES 11,269,246.00

    def test_closing_balance_matches_statement(self):
        result = extract_ncba_pdf(NCBA_PDF)
        assert result.raw_transactions[-1].balance_raw.replace(",", "") == "218029.5"

    def test_dates_are_iso(self):
        result = extract_ncba_pdf(NCBA_PDF)
        for t in result.raw_transactions:
            assert len(t.date_raw) == 10 and t.date_raw.count("-") == 2


def test_detect_ncba_does_not_false_positive_on_counterparty_mention(tmp_path):
    """A statement from a *different* bank whose transaction narration
    happens to mention NCBA as a counterparty (e.g. "FROM NCBA BANK
    M-PESA...") must not be misdetected as an NCBA statement — the header
    scan is intentionally limited to the first ~500 chars of page 1, well
    before any transaction row."""
    other_bank_pdf = f"{SAMPLES}/Deed Statement Jun 15 2026 (1).pdf"
    if not _can_open(other_bank_pdf):
        pytest.skip("counterparty-mention fixture missing or unreadable")
    assert detect_ncba(other_bank_pdf) is False
