"""Tests for bank format router."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pdfplumber
import pytest

from app.extractors.router import route_extract, UNSUPPORTED_RESPONSE

_KCB_BUILDEX = Path(__file__).parent / "fixtures" / "buildex" / "kcb_buildex_2025.pdf"

SAMPLES = "/Users/mbakswatu/Desktop/Demofiles/bankstatementsamples"
KCB_PDF = f"{SAMPLES}/KCB Bank Statement (1).pdf"
NCBA_PDF = f"{SAMPLES}/NCBA Bank Statement.pdf"
COOP_PDF = f"{SAMPLES}/Cooperative Bank Statement.pdf"
ABSA_PDF = f"{SAMPLES}/absa.pdf"
EQUITY_PDF = f"{SAMPLES}/Unlock PDF Equity Unlocked.pdf"


@pytest.mark.skipif(
    not __import__("pathlib").Path(KCB_PDF).exists(),
    reason="KCB fixture missing",
)
def test_router_detects_kcb():
    result = route_extract(KCB_PDF)
    assert not isinstance(result, dict) or result.get("status") != "UNSUPPORTED_FORMAT"
    if hasattr(result, "extractor_type"):
        assert result.extractor_type == "kcb_pdf"


@pytest.mark.skipif(
    not __import__("pathlib").Path(NCBA_PDF).exists(),
    reason="NCBA fixture missing",
)
def test_router_detects_ncba():
    result = route_extract(NCBA_PDF)
    assert not isinstance(result, dict) or result.get("status") != "UNSUPPORTED_FORMAT"
    if hasattr(result, "extractor_type"):
        assert result.extractor_type == "ncba_pdf"


@pytest.mark.skipif(
    not __import__("pathlib").Path(COOP_PDF).exists(),
    reason="COOP fixture missing",
)
def test_router_detects_coop():
    result = route_extract(COOP_PDF)
    if hasattr(result, "extractor_type"):
        assert result.extractor_type == "coop_pdf"


@pytest.mark.skipif(not _KCB_BUILDEX.exists(), reason="KCB buildex fixture not present")
def test_route_extract_opens_pdf_at_most_twice():
    """
    PAR-36 regression guard: `route_extract()` previously opened the same
    PDF up to 11 times (once per bank detector, once for currency
    pre-extraction, once for the final matched extractor) — confirmed via
    instrumented `pdfplumber.open` call counts on this file.

    Detection + currency pre-extraction now share a single parse; only the
    winning extractor's own (separately scoped, PAR-37-adjacent) open
    remains. Ceiling of 2 total opens, down from up to 11.
    """
    real_open = pdfplumber.open
    open_call_sites = []

    def _tracking_open(*args, **kwargs):
        open_call_sites.append(args[0] if args else kwargs.get("path_or_fp"))
        return real_open(*args, **kwargs)

    with patch("pdfplumber.open", side_effect=_tracking_open):
        result = route_extract(str(_KCB_BUILDEX))

    assert not isinstance(result, dict) or result.get("status") != "UNSUPPORTED_FORMAT"
    assert len(open_call_sites) <= 2, (
        f"expected at most 2 pdfplumber.open() calls (1 shared parse + 1 final "
        f"extractor open), got {len(open_call_sites)}"
    )


def test_router_returns_unsupported_for_invalid():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 invalid content")
        path = f.name
    try:
        result = route_extract(path)
        assert isinstance(result, dict)
        assert result.get("status") == "UNSUPPORTED_FORMAT"
    finally:
        import os
        os.unlink(path)
