"""
Regression tests for the OCR fallback path in audited_financials_extractor.py.

Background: _calculate_confidence() assumes that if a field key is present in
its input dict, the value is a real number — true for the coordinate-extraction
path (required fields are validated before confidence is ever calculated), not
true for OCR (every key is always set, with None on a failed regex match).
A document where OCR can't find "profit before tax" / "tax expense" used to
crash with an unhandled TypeError instead of returning a clean failure.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from app.extractors.audited_financials_extractor import extract_audited_financials_from_ocr

_FIXTURES = Path(__file__).parent
_SCANNED_FIXTURE = _FIXTURES / "scanned_equity_bank_statement.pdf"


def test_missing_pat_fields_returns_zero_confidence_not_crash(monkeypatch):
    """
    Unit-level pin: OCR text that contains no financial wording at all (so
    profit_before_tax_cents / tax_expense_cents / profit_after_tax_cents all
    resolve to None) must come back as a clean confidence=0 result, not raise.
    """
    import app.extractors.audited_financials_extractor as mod

    monkeypatch.setattr(
        mod, "_ocr_pdf_to_text", lambda pdf_path: "This page has no financial figures on it at all."
    )

    result = extract_audited_financials_from_ocr("unused-path.pdf")

    assert result["extraction_confidence"] == 0
    assert result["extraction_method"] == "tesseract_ocr"
    assert len(result["sha256_hash"]) == 64


def test_partial_pat_fields_returns_zero_confidence_not_crash(monkeypatch):
    """
    Same regression, but with one of the three PAT fields found and the other
    two missing — confirms the fix isn't accidentally only covering the
    all-three-missing case (None - None), but also int - None / None - int.
    """
    import app.extractors.audited_financials_extractor as mod

    monkeypatch.setattr(
        mod,
        "_ocr_pdf_to_text",
        lambda pdf_path: "Profit before tax 1,000,000 for the year.",
    )

    result = extract_audited_financials_from_ocr("unused-path.pdf")

    # On the TypeError path the function returns the same minimal skeleton as
    # total OCR failure — it does not partially keep the one field it found.
    assert result["extraction_confidence"] == 0
    assert result["extraction_method"] == "tesseract_ocr"
    assert "profit_before_tax_cents" not in result


@pytest.mark.skipif(
    not _SCANNED_FIXTURE.exists() or shutil.which("tesseract") is None,
    reason="scanned fixture or tesseract binary missing",
)
def test_real_scanned_pdf_smoke_test_does_not_crash():
    """
    Mechanical smoke test with the one real scanned PDF available locally.
    This is a bank statement, not an audited financial statement — used only
    to exercise the OCR code path end-to-end with a real Tesseract run,
    because no real scanned audited-financials PDF is available. It is the
    exact file that reproduced the original crash.
    """
    result = extract_audited_financials_from_ocr(str(_SCANNED_FIXTURE))
    assert result["extraction_confidence"] == 0
    assert result["extraction_method"] == "tesseract_ocr"
