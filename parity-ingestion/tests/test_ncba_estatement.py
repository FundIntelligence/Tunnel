"""Tests for the NCBA "e-Statement Of Account" template extractor (PAR-69).

Fixtures referenced directly from the real-samples client tree, never
committed (*.pdf is gitignored repo-wide) — same convention as
test_ncba.py. Skipped gracefully if absent.

The fixture password lives in a plaintext `NCBA Password.txt` next to the
statements themselves and is read from there at test time — it is never
hardcoded in this file, per PAR-69's explicit instruction not to commit the
fixture password anywhere outside the fixtures directory it already lives
in.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.extractors.ncba_extractor import (
    detect_ncba,
    detect_ncba_estatement,
    extract_ncba_estatement_pdf,
)

FIXTURE_DIR = (
    "tests/fixtures/real_samples/clients/sayuni/Finalleg/"
    "re_parity_x_sayuni_pilot_12/Bank Statements/NCBA"
)
PASSWORD_FILE = f"{FIXTURE_DIR}/NCBA Password.txt"
JAN_2024 = f"{FIXTURE_DIR}/NCBA_2024/NCBA_Jan2024.pdf"
JAN_2025 = f"{FIXTURE_DIR}/NCBA_2025/NCBA - JAN 2025.pdf"


def _load_password() -> str:
    path = pathlib.Path(PASSWORD_FILE)
    if not path.exists():
        return ""
    m = re.search(r"Password\s*-\s*(\S+)", path.read_text())
    return m.group(1) if m else ""


FIXTURE_PASSWORD = _load_password()


def _can_open(path: str, password: str) -> bool:
    if not pathlib.Path(path).exists():
        return False
    try:
        import pdfplumber

        with pdfplumber.open(path, password=password) as pdf:
            _ = pdf.pages[0].extract_text()
        return True
    except Exception:
        return False


def _to_cents(raw: str) -> int:
    if not raw:
        return 0
    sign = -1 if raw.strip().startswith("-") else 1
    clean = raw.replace(",", "").replace("-", "").strip()
    if "." in clean:
        whole, frac = clean.split(".", 1)
        frac = (frac + "00")[:2]
        return sign * (int(whole or 0) * 100 + int(frac))
    return sign * int(clean) * 100


pytestmark = pytest.mark.skipif(
    not _can_open(JAN_2024, FIXTURE_PASSWORD),
    reason="NCBA e-statement fixture or password file missing/unreadable",
)


class TestDetectNcbaEstatement:
    def test_detects_with_correct_password(self):
        assert detect_ncba_estatement(JAN_2024, password=FIXTURE_PASSWORD) is True

    def test_wrong_password_does_not_raise_and_returns_false(self):
        assert detect_ncba_estatement(JAN_2024, password="wrong-password") is False

    def test_missing_password_does_not_raise_and_returns_false(self):
        assert detect_ncba_estatement(JAN_2024, password=None) is False

    def test_older_ncba_detector_does_not_false_positive_without_password(self):
        # detect_ncba doesn't take a password at all; against a
        # password-protected file it must fail closed (False), not raise.
        assert detect_ncba(JAN_2024) is False


class TestExtractNcbaEstatementJan2024:
    """GREENFOREST FOODS LIMITED, Jan 2024, Business Current Account variant."""

    def test_extraction_succeeds(self):
        result = extract_ncba_estatement_pdf(JAN_2024, password=FIXTURE_PASSWORD)
        assert result.extraction_status == "success"
        assert result.extractor_type == "ncba_estatement_pdf"
        assert len(result.raw_transactions) == 140

    def test_dates_are_iso(self):
        result = extract_ncba_estatement_pdf(JAN_2024, password=FIXTURE_PASSWORD)
        for t in result.raw_transactions:
            assert len(t.date_raw) == 10 and t.date_raw.count("-") == 2

    def test_direction_reconciles_exactly_against_statement_totals(self):
        """Strongest available accuracy signal, same technique used to
        confirm PAR-14's bug: the statement's own printed "Payments In" /
        "Payments Out" / "Closing Balance" figures must match the sum of
        extracted credits/debits and the final running balance exactly, to
        the cent — not just "the parser ran without erroring"."""
        result = extract_ncba_estatement_pdf(JAN_2024, password=FIXTURE_PASSWORD)
        total_debit = sum(_to_cents(t.debit_raw) for t in result.raw_transactions)
        total_credit = sum(_to_cents(t.credit_raw) for t in result.raw_transactions)
        assert total_debit == 1837870722  # KES 18,378,707.22 printed "Payments Out"
        assert total_credit == 1776097836  # KES 17,760,978.36 printed "Payments In"
        assert result.raw_transactions[-1].balance_raw.replace(",", "") == "813198.41"

    def test_no_warnings_on_clean_fixture(self):
        result = extract_ncba_estatement_pdf(JAN_2024, password=FIXTURE_PASSWORD)
        assert result.warnings == []


@pytest.mark.skipif(
    not _can_open(JAN_2025, FIXTURE_PASSWORD),
    reason="second NCBA e-statement fixture missing/unreadable",
)
class TestExtractNcbaEstatementJan2025:
    """Second real fixture, different statement period and account variant
    ("Go Banking" vs. "Business Current Account") — confirms the parser
    generalizes rather than being overfit to one file, including a
    lowercase-'of' header variant ("e-Statement of Account")."""

    def test_detects(self):
        assert detect_ncba_estatement(JAN_2025, password=FIXTURE_PASSWORD) is True

    def test_direction_reconciles_exactly_against_statement_totals(self):
        result = extract_ncba_estatement_pdf(JAN_2025, password=FIXTURE_PASSWORD)
        total_debit = sum(_to_cents(t.debit_raw) for t in result.raw_transactions)
        total_credit = sum(_to_cents(t.credit_raw) for t in result.raw_transactions)
        assert total_debit == 245490735  # KES 2,454,907.35 printed "Payments Out"
        assert total_credit == 278930855  # KES 2,789,308.55 printed "Payments In"
        assert result.raw_transactions[-1].balance_raw.replace(",", "") == "381715.15"
