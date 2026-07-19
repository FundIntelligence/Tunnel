"""
Tests for the single-parse document layer (PAR-36). The key property under
test is call-count: `route_extract()` previously opened the same PDF up to
11 times (once per detector, once for currency pre-extraction, once for the
final extractor) — confirmed via instrumented `pdfplumber.open` calls per
the PAR-36 ticket. `parse_pdf()` must open exactly once no matter how many
pages or how many times downstream code reads `.text`/`.words`.
"""
from pathlib import Path
from unittest.mock import patch

import pdfplumber
import pytest

from app.extractors.pdf_document import NormalizedDocument, as_document, parse_pdf

_FIXTURE = Path(__file__).parent / "fixtures" / "buildex" / "kcb_buildex_2025.pdf"


@pytest.mark.skipif(not _FIXTURE.exists(), reason="KCB buildex fixture not present")
def test_parse_pdf_opens_file_exactly_once():
    real_open = pdfplumber.open
    with patch("app.extractors.pdf_document.pdfplumber.open", wraps=real_open) as mock_open:
        with parse_pdf(str(_FIXTURE)) as doc:
            # Touch text and words on every page — none of this should
            # trigger a second `pdfplumber.open()` call.
            for page in doc.pages:
                _ = page.text
                _ = page.words
        mock_open.assert_called_once_with(str(_FIXTURE))


@pytest.mark.skipif(not _FIXTURE.exists(), reason="KCB buildex fixture not present")
def test_parse_pdf_extracts_all_pages_with_text():
    with parse_pdf(str(_FIXTURE)) as doc:
        assert len(doc.pages) == 126
        assert doc.pages[0].text  # page 0 has extractable text
        assert doc.pages[0].rotation == 90


@pytest.mark.skipif(not _FIXTURE.exists(), reason="KCB buildex fixture not present")
def test_words_are_cached_not_recomputed():
    with parse_pdf(str(_FIXTURE)) as doc:
        page = doc.pages[0]
        first = page.words
        second = page.words
        assert first is second  # same object: computed once, cached


@pytest.mark.skipif(not _FIXTURE.exists(), reason="KCB buildex fixture not present")
def test_text_upto_matches_manual_join():
    with parse_pdf(str(_FIXTURE)) as doc:
        expected = " ".join(p.text for p in doc.pages[:2] if p.text)
        assert doc.text_upto(2) == expected


@pytest.mark.skipif(not _FIXTURE.exists(), reason="KCB buildex fixture not present")
def test_as_document_reuses_an_existing_document_without_reopening():
    with parse_pdf(str(_FIXTURE)) as doc:
        real_open = pdfplumber.open
        with patch("app.extractors.pdf_document.pdfplumber.open", wraps=real_open) as mock_open:
            with as_document(doc) as reused:
                assert reused is doc
            mock_open.assert_not_called()


@pytest.mark.skipif(not _FIXTURE.exists(), reason="KCB buildex fixture not present")
def test_as_document_opens_and_closes_when_given_a_path():
    with as_document(str(_FIXTURE)) as doc:
        assert isinstance(doc, NormalizedDocument)
        assert len(doc.pages) == 126
    # Underlying pdfplumber.PDF should be closed after the `with` block —
    # accessing .pages triggers no error since it's a plain list already
    # built eagerly, but the stream itself should be closed.
    assert doc._pdf.stream.closed
