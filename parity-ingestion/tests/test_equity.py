"""Tests for Equity Bank PDF extractor."""
from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest

from app.extractors.equity_extractor import (
    _detect_split_transaction_header,
    _parse_business_txn_line,
    detect_equity,
    detect_equity_f1,
    extract_equity_pdf,
    extract_equity_f1_pdf,
)
from app.extractors.router import route_extract
from app.normaliser import normalise_all

SAMPLES = "/Users/mbakswatu/Desktop/Demofiles/bankstatementsamples"
EQUITY_PDF = f"{SAMPLES}/Unlock PDF Equity Unlocked.pdf"
# April 2025: split column header ("Transacti" / "on Date") + split date lines (DD-MM- / YYYY on next lines)
EQUITY_APR_2025 = (
    "/Users/mbakswatu/Desktop/parity/sayuni/2025/pdf/"
    "Sassy Cosmetics - Equity Bank - 1180279761781 - Apr 2025.pdf"
)
EQUITY_FEB_2025 = (
    "/Users/mbakswatu/Desktop/parity/sayuni/2025/pdf/"
    "Sassy Cosmetics - Equity Bank - 1180279761781 - Feb 2025.pdf"
)
# CAA business account (GBFund calls it "F1"; "F1" does not appear in the document).
# Fixture is committed to the repo — always available, no skipif needed.
EQUITY_F1_PDF = str(
    Path(__file__).parent
    / "fixtures"
    / "real_samples"
    / "bank_samples"
    / "Equity Bank Statement F1.pdf"
)


def _amount_cents(norm_txn) -> int:
    debit = norm_txn.debit_cents or 0
    credit = norm_txn.credit_cents or 0
    return credit - debit


@pytest.mark.skipif(
    not __import__("pathlib").Path(EQUITY_PDF).exists(),
    reason="Equity fixture missing",
)
class TestEquityExtractor:
    def test_dr_balance_positive_overdrawn(self):
        result = extract_equity_pdf(EQUITY_PDF)
        normalise_all(result)
        overdrawn = [t for t in result.raw_transactions if t.balance_is_overdrawn]
        for t in overdrawn:
            norm = result.normalised_transactions[t.row_index]
            assert norm.balance_cents is not None
            assert norm.balance_cents > 0
            assert isinstance(norm.balance_cents, int)

    def test_hyphen_date_format(self):
        result = extract_equity_pdf(EQUITY_PDF)
        for t in result.raw_transactions:
            if t.date_raw and len(t.date_raw) == 10:
                assert t.date_raw[4] == "-" and t.date_raw[7] == "-"

    def test_opening_balance_zero(self):
        result = extract_equity_pdf(EQUITY_PDF)
        normalise_all(result)
        opening = [
            t for t in result.normalised_transactions
            if "OPENING" in (t.description or "").upper() or "B/FWD" in (t.description or "").upper()
        ]
        if opening:
            for t in opening:
                assert _amount_cents(t) == 0

    def test_page_total_excluded(self):
        result = extract_equity_pdf(EQUITY_PDF)
        for t in result.raw_transactions:
            assert "Page Total" not in (t.description or "")

    def test_truncated_description_no_raise(self):
        result = extract_equity_pdf(EQUITY_PDF)
        assert result.extraction_status in ("success", "needs_review")

    def test_no_floats(self):
        result = extract_equity_pdf(EQUITY_PDF)
        normalise_all(result)
        for t in result.normalised_transactions:
            if t.debit_cents is not None:
                assert isinstance(t.debit_cents, int)
            if t.credit_cents is not None:
                assert isinstance(t.credit_cents, int)
            if t.balance_cents is not None:
                assert isinstance(t.balance_cents, int)


@pytest.mark.skipif(
    not Path(EQUITY_APR_2025).exists(),
    reason="April 2025 Equity PDF fixture missing",
)
class TestEquityApril2025SplitHeader:
    def test_split_transaction_header_detected(self):
        with pdfplumber.open(EQUITY_APR_2025) as pdf:
            lines = pdf.pages[0].extract_text().split("\n")
        assert _detect_split_transaction_header(lines)

    def test_april_2025_extracts_split_date_layout(self):
        """
        PDF header shows Total Search Results: 3190; coordinate-based split-date
        extraction should match that count (line-based path dropped ~904 rows).
        """
        result = extract_equity_pdf(EQUITY_APR_2025)
        assert len(result.raw_transactions) == 3190


def test_business_parser_accepts_single_date_customer_reference_layout():
    line = "01-02-2025 POS SALE REF123 12,345.00 1,234,567.00"
    parsed, bal = _parse_business_txn_line(line, "", previous_balance=130000000)
    assert parsed is not None
    assert parsed["date_raw"] == "01-02-2025"
    assert parsed["money_out"] == "12345.00"
    assert parsed["money_in"] == ""
    assert parsed["balance_raw"] == "1,234,567.00"
    assert "REF123" in parsed["particulars"]
    assert bal == 123456700


@pytest.mark.skipif(
    not Path(EQUITY_FEB_2025).exists(),
    reason="February 2025 Equity PDF fixture missing",
)
def test_february_2025_customer_reference_layout_extracts():
    result = extract_equity_pdf(EQUITY_FEB_2025)
    assert len(result.raw_transactions) == 2673


def _to_cents_signed(raw: str) -> int:
    """Parse a raw balance/amount string (possibly negative) to integer cents."""
    if not raw:
        return 0
    s = raw.replace(",", "")
    neg = s.startswith("-")
    s = s.lstrip("-")
    parts = s.split(".")
    whole = int(parts[0]) if parts[0] else 0
    frac = int(parts[1].ljust(2, "0")[:2]) if len(parts) > 1 else 0
    v = whole * 100 + frac
    return -v if neg else v


class TestEquityF1Extractor:
    """Equity CAA / "F1" business account format (PAR-65).

    "CAA" is the product name printed in the document.
    "F1" is GBFund's colloquial alias and does not appear in the PDF.
    Fixture: FORTMORE ENTERPRISE LIMITED, account 0220284686225,
    period 31-01-2025 to 07-03-2025 (78 pages, 1 000 transactions).
    """

    def test_detector_fires(self):
        """detect_equity_f1 must return True for this fixture."""
        assert detect_equity_f1(EQUITY_F1_PDF)

    def test_row_count(self):
        """Statement contains exactly 1 000 transaction rows (verified against
        the Grand Total recap on page 78)."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        assert len(result.raw_transactions) == 1000

    def test_grand_total_debit_credit(self):
        """Sum of extracted debits and credits must match the Grand Total line
        printed on page 78: Debit 6,289,983.99 / Credit 6,276,322.36."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        total_debit = sum(
            _to_cents_signed(t.debit_raw) for t in result.raw_transactions
        )
        total_credit = sum(
            _to_cents_signed(t.credit_raw) for t in result.raw_transactions
        )
        assert total_debit == 628_998_399   # KES 6,289,983.99
        assert total_credit == 627_632_236  # KES 6,276,322.36

    def test_running_balance_reconciles_every_row(self):
        """Strongest accuracy signal: recompute the running balance from
        debit/credit deltas and require it to match the statement's own
        printed balance for every row (999 transitions in this fixture)."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        rows = [t for t in result.raw_transactions if t.date_raw]
        prev_bal = None
        checked = 0
        for t in rows:
            bal = _to_cents_signed(t.balance_raw) if t.balance_raw else None
            debit = _to_cents_signed(t.debit_raw)
            credit = _to_cents_signed(t.credit_raw)
            if bal is None:
                continue
            if prev_bal is not None:
                assert abs((prev_bal - debit + credit) - bal) <= 1, (
                    f"Balance mismatch at row {t.row_index}: "
                    f"expected {prev_bal - debit + credit}, got {bal} "
                    f"(debit={debit}, credit={credit})"
                )
                checked += 1
            prev_bal = bal
        assert checked >= 990

    def test_final_balance(self):
        """Last transaction's printed balance must be 15,899.76 (KES 1,589,976 cents),
        matching the Grand Total recap on page 78."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        last_bal = [t.balance_raw for t in result.raw_transactions if t.balance_raw][-1]
        assert _to_cents_signed(last_bal) == 1_589_976  # KES 15,899.76

    def test_no_floats(self):
        """All monetary values must be integer cents after normalisation — no floats."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        normalise_all(result)
        for t in result.normalised_transactions:
            if t.debit_cents is not None:
                assert isinstance(t.debit_cents, int)
            if t.credit_cents is not None:
                assert isinstance(t.credit_cents, int)
            if t.balance_cents is not None:
                assert isinstance(t.balance_cents, int)

    def test_no_warnings(self):
        """Clean fixture — extraction must complete with zero warnings."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        assert result.warnings == []

    def test_router_selects_f1_extractor(self):
        """No prior detector/extractor handled this layout (net-new format,
        PAR-65) — confirm the router actually dispatches to
        extract_equity_f1_pdf rather than falling through to
        UNSUPPORTED_FORMAT or a mismatched Equity variant."""
        result = route_extract(EQUITY_F1_PDF)
        assert not isinstance(result, dict), f"expected ExtractionResult, got {result}"
        assert result.row_count == 1000

    def test_negative_balance_captured(self):
        """A momentary overdraft prints a signed running balance
        ("-99,707.40") rather than a "Dr" suffix. It must be captured with
        its sign, not read as positive — misreading it flips the
        debit/credit direction of whichever row follows, since direction is
        inferred from whether the balance rose or fell."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        negative_balances = [
            t for t in result.raw_transactions if (t.balance_raw or "").startswith("-")
        ]
        assert len(negative_balances) >= 1

    def test_no_grand_total_row_or_trailer_leak(self):
        """The end-of-statement "Grand Total" recap, and the page
        signature/stamp block after it ("END" + trailer code), must never
        appear as or leak into a transaction row's description."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        for t in result.raw_transactions:
            assert "GRAND TOTAL" not in (t.description or "").upper()
        assert "AG3508220250730093526" not in result.raw_transactions[-1].description

    def test_instrument_id_continuation_attached_to_owning_row(self):
        """Instrument Id + counterparty name print as continuation line(s)
        AFTER the date/amount line, so they belong to that same row — the
        opposite ordering from the existing business-format extractor, where
        narrative lines precede the date/amount line as a prefix to the
        *next* row. Getting this backwards silently shifts every
        continuation string onto the wrong transaction."""
        result = extract_equity_f1_pdf(EQUITY_F1_PDF)
        first = result.raw_transactions[0]
        assert "TAV160MMYH" in first.description
        assert "FLORENCE" in first.description.upper()
