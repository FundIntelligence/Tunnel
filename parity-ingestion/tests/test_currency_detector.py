"""
Tests for currency_detector.py — L1 deterministic regex detection.

All tests run offline (no PDF required for most).
Fixture-based tests use existing PDFs in tests/fixtures/.
"""
import os
import sys

import pytest

# Ensure parity-ingestion package is on the path
_pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.extractors.currency_detector import detect, detect_from_pages


# ── P1: Explicit declarations ──────────────────────────────────────────────────

class TestP1ExplicitDeclarations:
    def test_currency_colon(self):
        assert detect("Currency: KES\nAccount details") == "KES"

    def test_currency_colon_usd(self):
        assert detect("Currency: USD\nAccount details") == "USD"

    def test_account_currency_label(self):
        assert detect("Account Currency: UGX") == "UGX"

    def test_statement_currency(self):
        assert detect("Statement Currency XOF\n") == "XOF"

    def test_ccy_abbreviation(self):
        assert detect("Ccy: RWF\nDate") == "RWF"

    def test_all_amounts_in(self):
        assert detect("All amounts in UGX\nDate Description") == "UGX"

    def test_all_amount_singular_in(self):
        assert detect("All amount in NGN\nTransaction") == "NGN"

    def test_amounts_in(self):
        assert detect("Amounts in GHS\nBalance") == "GHS"

    def test_case_insensitive(self):
        assert detect("currency: kes") == "KES"

    def test_currency_of_account(self):
        assert detect("Currency of Account: TZS\nStatement") == "TZS"


# ── P2: ISO codes in header zone ───────────────────────────────────────────────

class TestP2ISOHeaderZone:
    def test_kes_in_header(self):
        # ISO code within first 500 chars, not via explicit declaration
        assert detect("STATEMENT OF ACCOUNT\nKES balance brought forward") == "KES"

    def test_ugx_in_header(self):
        assert detect("Bank Statement\nUGX Account\n") == "UGX"

    def test_iso_code_not_found_in_body_only(self):
        # Code appears only beyond 500 chars — should not match P2, may match P4
        prefix = "X" * 501
        result = detect(prefix + " UGX 5,000")
        # P4 inline match kicks in (first 2000 chars)
        assert result == "UGX"

    def test_xaf_explicit_not_cfa_skip(self):
        # XAF via explicit declaration should resolve (P1 override)
        assert detect("Account Currency: XAF\n") == "XAF"

    def test_xof_explicit_not_cfa_skip(self):
        assert detect("Currency: XOF\n") == "XOF"

    def test_xaf_header_only_is_skipped(self):
        # XAF as bare ISO code in header (no explicit declaration) is CFA-ambiguous
        # The detector should skip it and fall through — only resolves via country in L2
        result = detect("XAF account\nTransactions")
        # P2 skips CFA codes; P3/P4 won't find anything else
        assert result is None


# ── P3: Local symbol patterns ──────────────────────────────────────────────────

class TestP3LocalSymbols:
    def test_ksh(self):
        assert detect("Ksh 50,000 opening balance") == "KES"

    def test_ksh_caps(self):
        assert detect("KSh 1,200 credit") == "KES"

    def test_k_dot_sh(self):
        assert detect("K.Sh 800") == "KES"

    def test_kshs_plural(self):
        """Audited financial statements commonly write the abbreviation as
        'KShs' (trailing s) rather than 'KSh' — e.g. 'Kenya Shillings (KShs)'
        in an accounting-policy note."""
        assert detect("presented in Kenya Shillings (KShs)") == "KES"

    def test_kshs_lowercase_plural(self):
        assert detect("Amounts shown in Kshs '000") == "KES"

    def test_ushs(self):
        assert detect("UShs 2,300,000 credit") == "UGX"

    def test_u_dot_shs(self):
        assert detect("U.Shs 150,000") == "UGX"

    def test_ush(self):
        assert detect("Ush 45,000 debit") == "UGX"

    def test_rfw(self):
        assert detect("RFw 300,000 transfer") == "RWF"

    def test_frw(self):
        assert detect("FRw 180,000") == "RWF"

    def test_frw_alt(self):
        assert detect("Frw 10,000") == "RWF"

    def test_gh_cedis(self):
        assert detect("GH₵ 4,500 transaction") == "GHS"

    def test_gh_c(self):
        assert detect("GHC 1,000 balance") == "GHS"

    def test_naira_symbol(self):
        assert detect("₦ 180,000 transfer") == "NGN"

    def test_naira_word(self):
        assert detect("Naira 500,000 credit") == "NGN"

    def test_birr(self):
        assert detect("Birr 12,500 remittance") == "ETB"

    def test_zar_r_space_digits(self):
        assert detect("Balance R 15,000") == "ZAR"


# ── P3: CFA / FCFA ambiguity ───────────────────────────────────────────────────

class TestCFAAmbiguity:
    def test_fcfa_returns_none(self):
        assert detect("FCFA 250,000 virement") is None

    def test_cfa_returns_none(self):
        assert detect("CFA 100,000 solde") is None

    def test_cfa_uppercase_returns_none(self):
        assert detect("CFA 50,000") is None


# ── P4: Inline amount patterns ─────────────────────────────────────────────────

class TestP4InlineAmounts:
    def test_kes_inline(self):
        assert detect("Available Balance: KES 574,326.29") == "KES"

    def test_ugx_inline(self):
        assert detect("Closing balance UGX 3,400,000") == "UGX"

    def test_ngn_inline(self):
        assert detect("Total NGN 9,000,000.00") == "NGN"

    def test_usd_inline(self):
        assert detect("USD 50,000 transfer") == "USD"

    def test_inline_case_insensitive(self):
        assert detect("kes 10,000") == "KES"


# ── Edge cases ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_string(self):
        assert detect("") is None

    def test_whitespace_only(self):
        assert detect("   \n  ") is None

    def test_no_currency_info(self):
        assert detect("No currency info here at all") is None

    def test_does_not_guess(self):
        assert detect("Date    Description    Amount") is None

    def test_detect_from_pages_concatenates(self):
        pages = ["Currency: UGX", "Transaction data", "More data"]
        assert detect_from_pages(pages) == "UGX"

    def test_detect_from_pages_max_3(self):
        pages = ["nothing", "nothing", "nothing", "Currency: KES"]
        # 4th page excluded
        assert detect_from_pages(pages) is None

    def test_detect_from_pages_empty_list(self):
        assert detect_from_pages([]) is None

    def test_p1_wins_over_p4(self):
        # Explicit declaration at top, different ISO code inline
        text = "Currency: UGX\n" + "USD 5,000 transfer\n"
        assert detect(text) == "UGX"


# ── Fixture-based tests (real PDF text) ───────────────────────────────────────

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def equity_fixture_text():
    path = os.path.join(FIXTURES_DIR, "buildex", "equity_buildex_2025.pdf")
    if not os.path.exists(path):
        pytest.skip("Equity fixture not found")
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return " ".join(p.extract_text() or "" for p in pdf.pages[:2])


@pytest.fixture
def kcb_fixture_text():
    path = os.path.join(FIXTURES_DIR, "buildex", "kcb_buildex_2025.pdf")
    if not os.path.exists(path):
        pytest.skip("KCB fixture not found")
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return " ".join(p.extract_text() or "" for p in pdf.pages[:2])


def test_equity_fixture_detects_kes(equity_fixture_text):
    assert detect(equity_fixture_text) == "KES"


def test_kcb_fixture_detects_kes(kcb_fixture_text):
    assert detect(kcb_fixture_text) == "KES"


def test_stanbic_fixture_returns_none():
    """Stanbic uses CID-encoded fonts — pdfplumber returns garbage. Should return None."""
    path = os.path.join(FIXTURES_DIR, "stanbic_zuridi.pdf")
    if not os.path.exists(path):
        pytest.skip("Stanbic fixture not found")
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        text = " ".join(p.extract_text() or "" for p in pdf.pages[:2])
    # CID-encoded text should yield None (Stanbic uses OCR path)
    result = detect(text)
    assert result is None
