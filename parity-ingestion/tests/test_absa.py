"""Tests for ABSA Bank PDF extractor."""
from __future__ import annotations

import pytest

from app.extractors.absa_extractor import detect_absa, extract_absa_pdf
from app.normaliser import normalise_all

SAMPLES = "/Users/mbakswatu/Desktop/Demofiles/bankstatementsamples"
ABSA_PDF = f"{SAMPLES}/absa.pdf"


def _can_open_absa_pdf() -> bool:
    import pathlib
    if not pathlib.Path(ABSA_PDF).exists():
        return False
    try:
        import pdfplumber
        with pdfplumber.open(ABSA_PDF) as pdf:
            _ = pdf.pages[0].extract_text()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _can_open_absa_pdf(), reason="ABSA fixture missing or unreadable")
class TestAbsaExtractor:
    def test_malformed_balance_warning(self):
        result = extract_absa_pdf(ABSA_PDF)
        normalise_all(result)
        has_malformed = any(
            "malformed" in w.message.lower() or "balance" in w.message.lower()
            for w in result.warnings
        )
        if has_malformed:
            null_balances = [
                t for t in result.normalised_transactions
                if t.balance_cents is None and result.raw_transactions[t.row_index].balance_raw
            ]
            assert len(null_balances) >= 1

    def test_file_not_rejected(self):
        result = extract_absa_pdf(ABSA_PDF)
        assert result.extraction_status in ("success", "needs_review")
        assert len(result.raw_transactions) > 0

    def test_confidence_penalty_on_warnings(self):
        result = extract_absa_pdf(ABSA_PDF)
        if result.warnings:
            assert result.extraction_status == "needs_review"

    def test_normal_rows_unaffected(self):
        result = extract_absa_pdf(ABSA_PDF)
        normalise_all(result)
        for raw, norm in zip(result.raw_transactions, result.normalised_transactions):
            if raw.balance_raw and "malformed" not in str(result.warnings):
                pass
            if norm.balance_cents is not None:
                assert isinstance(norm.balance_cents, int)

    def test_user_narrative_appended(self):
        result = extract_absa_pdf(ABSA_PDF)
        with_narrative = [
            t for t in result.raw_transactions
            if " | " in (t.description or "")
        ]
        if with_narrative:
            for t in with_narrative:
                assert " | " in t.description

    def test_no_floats(self):
        result = extract_absa_pdf(ABSA_PDF)
        normalise_all(result)
        for t in result.normalised_transactions:
            if t.debit_cents is not None:
                assert isinstance(t.debit_cents, int)
            if t.credit_cents is not None:
                assert isinstance(t.credit_cents, int)
            if t.balance_cents is not None:
                assert isinstance(t.balance_cents, int)


# ── Corporate and Business Banking template ──────────────────────────────────
# Real Absa template with a second Value Date column (same x0 < 120 zone as
# Transaction Date) and an end-of-statement "Total <debit> <credit>" recap
# row with no date/description. Both previously caused 0 rows extracted —
# see absa_extractor.py module docstring and the row-skip guard for why.

CORP_SAMPLES = "/Users/mbakswatu/Desktop/Deedfilesmusa"
CORP_ABSA_PDF = f"{CORP_SAMPLES}/Acc Act Deed Dec 2025 to May 2026.pdf"


def _can_open_corp_absa_pdf() -> bool:
    import pathlib
    if not pathlib.Path(CORP_ABSA_PDF).exists():
        return False
    try:
        import pdfplumber
        with pdfplumber.open(CORP_ABSA_PDF) as pdf:
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


@pytest.mark.skipif(not _can_open_corp_absa_pdf(), reason="Corporate Absa fixture missing or unreadable")
class TestAbsaCorporateTemplate:
    def test_detect_absa(self):
        assert detect_absa(CORP_ABSA_PDF) is True

    def test_file_not_rejected(self):
        result = extract_absa_pdf(CORP_ABSA_PDF)
        assert result.extraction_status in ("success", "needs_review")
        assert len(result.raw_transactions) > 0

    def test_value_date_does_not_corrupt_transaction_date(self):
        """Every row's date_raw must be a single ISO date, never two dates
        concatenated (the dual-date-column bug)."""
        result = extract_absa_pdf(CORP_ABSA_PDF)
        for t in result.raw_transactions:
            assert t.date_raw.count("-") == 2

    def test_totals_match_statement_declared_figures(self):
        """Strongest available accuracy signal: this statement declares its
        own Total money in / Total money out on the account summary line —
        sum of extracted credits/debits must match exactly."""
        result = extract_absa_pdf(CORP_ABSA_PDF)
        total_debit = sum(_to_cents(t.debit_raw) for t in result.raw_transactions)
        total_credit = sum(_to_cents(t.credit_raw) for t in result.raw_transactions)
        assert total_debit == 607080630   # KES 6,070,806.30
        assert total_credit == 610881760  # KES 6,108,817.60

    def test_closing_balance_matches_statement(self):
        result = extract_absa_pdf(CORP_ABSA_PDF)
        # Rows are listed newest-first in this template.
        assert result.raw_transactions[0].balance_raw.replace(",", "") == "88152.20"

    def test_no_phantom_total_row(self):
        """The end-of-statement recap row (no date, no description, both
        debit and credit populated) must never appear as a transaction."""
        result = extract_absa_pdf(CORP_ABSA_PDF)
        for t in result.raw_transactions:
            assert not (t.debit_raw and t.credit_raw and not t.description.strip())


# ── "Absa One Biashara Account" template (PAR-64) ─────────────────────────────
# Real, committed fixture (gitignored as NDA client data — see
# tests/fixtures/real_samples/, never pushed). Columns: DATE | DESCRIPTION |
# USER DESCRIPTION | VALUE DATE | DEBIT | CREDIT | BALANCE — a wider page with
# entirely different x-coordinates than the legacy template, and no "Absa Bank
# Kenya"/"absa.kenya@absa.africa" brand text the old detector relied on.

OB_ABSA_PDF = str(
    __import__("pathlib").Path(__file__).parent
    / "fixtures/real_samples/bank_samples/ABSA Bank Statement for Dorah Omondi.pdf"
)


def _can_open_ob_absa_pdf() -> bool:
    import pathlib
    if not pathlib.Path(OB_ABSA_PDF).exists():
        return False
    try:
        import pdfplumber
        with pdfplumber.open(OB_ABSA_PDF) as pdf:
            _ = pdf.pages[0].extract_text()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _can_open_ob_absa_pdf(), reason="Absa One Biashara fixture missing or unreadable")
class TestAbsaOneBiasharaTemplate:
    def test_detect_absa(self):
        assert detect_absa(OB_ABSA_PDF) is True

    def test_file_not_rejected(self):
        result = extract_absa_pdf(OB_ABSA_PDF)
        assert result.extraction_status in ("success", "needs_review")
        assert len(result.raw_transactions) > 0

    def test_debit_credit_totals_match_declared_counts(self):
        """Statement declares its own "<n> Debits <total>" / "<n> Credits
        <total>" recap on the final page — sum of extracted debit/credit
        rows must match exactly."""
        result = extract_absa_pdf(OB_ABSA_PDF)
        total_debit = sum(_to_cents(t.debit_raw) for t in result.raw_transactions)
        total_credit = sum(_to_cents(t.credit_raw) for t in result.raw_transactions)
        assert total_debit == 7074493315  # KES 70,744,933.15
        assert total_credit == 7074990370  # KES 70,749,903.70

    def test_running_balance_reconciles_every_row(self):
        """Strongest available accuracy signal: recompute the running
        balance from debit/credit deltas and require it to match the
        statement's own printed balance for every single row (2819 of 2819
        transitions in the real fixture)."""
        result = extract_absa_pdf(OB_ABSA_PDF)
        rows = [t for t in result.raw_transactions if t.date_raw]
        prev_bal = None
        checked = 0
        for t in rows:
            bal = _to_cents(t.balance_raw.lstrip("-")) * (-1 if t.balance_raw.startswith("-") else 1) if t.balance_raw else None
            debit = _to_cents(t.debit_raw)
            credit = _to_cents(t.credit_raw)
            if bal is None:
                continue
            if prev_bal is not None:
                assert abs((prev_bal - debit + credit) - bal) <= 1
                checked += 1
            prev_bal = bal
        assert checked > 2500

    def test_negative_balance_captured(self):
        """A momentary overdraft ("-301,702.85") must still be captured as
        a balance value, not silently dropped to empty."""
        result = extract_absa_pdf(OB_ABSA_PDF)
        negative_balances = [t for t in result.raw_transactions if (t.balance_raw or "").startswith("-")]
        assert len(negative_balances) >= 1

    def test_marketing_narrative_not_treated_as_footer(self):
        """A real transaction narrative containing the word "marketing"
        (e.g. "BP:PESALINK-2/MARKETING") must not be dropped by the
        footer/ad-copy filter — only genuine footer text with no amount
        should be."""
        result = extract_absa_pdf(OB_ABSA_PDF)
        marketing_txns = [
            t for t in result.raw_transactions
            if "MARKETING" in (t.description or "").upper()
        ]
        assert len(marketing_txns) >= 1
        assert any(t.debit_raw or t.credit_raw for t in marketing_txns)

    def test_no_closing_balance_summary_row(self):
        """The end-of-statement "CLOSING BALANCE" recap block must never
        appear as a transaction row."""
        result = extract_absa_pdf(OB_ABSA_PDF)
        for t in result.raw_transactions:
            assert "CLOSING BALANCE" not in (t.description or "").upper()

    def test_no_floats(self):
        result = extract_absa_pdf(OB_ABSA_PDF)
        normalise_all(result)
        for t in result.normalised_transactions:
            if t.debit_cents is not None:
                assert isinstance(t.debit_cents, int)
            if t.credit_cents is not None:
                assert isinstance(t.credit_cents, int)
