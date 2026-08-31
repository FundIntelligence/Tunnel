"""
Single-parse PDF layer.

`route_extract()` previously opened the same PDF up to 11 times: once per
bank detector (10 formats), once more for currency pre-extraction, and once
more inside whichever extractor ultimately matched. Confirmed via
instrumented `pdfplumber.open` call counts (PAR-36 ticket).

`parse_pdf()` opens the file exactly once and hands every downstream
consumer — currency detection, bank-format detection — the same
already-extracted per-page text. Word extraction stays lazy per page (only
the winning extractor needs word-level positions, not every detector), but
is cached and routed through one explicit, documented tolerance
configuration instead of ~10 bare `page.extract_words()` calls scattered
across bank-specific extractor files with implicit defaults.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, List, Optional, Union

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect

# Explicit word-grouping tolerances. Previously an implicit pdfplumber
# default (`extract_words()` with no args) repeated ad hoc across ~10 bank
# extractors; pdfplumber's own default is x_tolerance=3, y_tolerance=3, so
# this preserves existing behavior while making the contract a single,
# documented, testable value instead of an implicit black box.
WORD_X_TOLERANCE = 3
WORD_Y_TOLERANCE = 3


class NormalizedPage:
    """One page of a single-parsed document. `text`, `words`, and `tables`
    are all extracted lazily and cached (PAR-216) -- format detection only
    ever reads the first ~2 pages' `text` (`NormalizedDocument.text_upto`),
    so eagerly running pdfplumber's `extract_text()` for every page at
    parse time (the previous behavior, and the docstring's own claim that
    doing so was "cheap") wasted real work and real memory on a large
    document: confirmed as a real, measured factor in a production OOM on a
    451-page statement (2Gi container limit, ~2076 MiB used) -- the other,
    larger factor being the double-parse this same ticket also fixed
    (`extract_equity_clms_pdf` no longer re-opens the file from scratch).
    Only the page(s) actually read ever pay the `extract_text()` cost now."""

    def __init__(self, page_number: int, page: "pdfplumber.page.Page"):
        self.page_number = page_number  # 1-indexed
        self.rotation: int = page.rotation
        self.width: float = page.width
        self.height: float = page.height
        self._page = page
        self._text: Optional[str] = None
        self._words: Optional[List[dict]] = None
        self._tables: Optional[list] = None

    @property
    def text(self) -> str:
        """Lazy, cached passthrough to pdfplumber's `extract_text()`."""
        if self._text is None:
            self._text = self._page.extract_text() or ""
        return self._text

    @property
    def words(self) -> List[dict]:
        """Upright, rotation-corrected word dicts: ``{text, x0, x1, top,
        bottom}``. This *is* pdfplumber's own `extract_words()` — pdfplumber
        already rotation-corrects internally — called once per page and
        cached, with the tolerance contract made explicit via
        `WORD_X_TOLERANCE`/`WORD_Y_TOLERANCE` above instead of left as a
        bare-call implicit default. Every bank extractor's x-threshold
        column logic assumes this exact shape and convention."""
        if self._words is None:
            self._words = self._page.extract_words(
                x_tolerance=WORD_X_TOLERANCE, y_tolerance=WORD_Y_TOLERANCE
            )
        return self._words

    def extract_tables(self) -> list:
        """Lazy, cached passthrough to pdfplumber's table extraction."""
        if self._tables is None:
            self._tables = self._page.extract_tables()
        return self._tables

    def flush_cache(self) -> None:
        """Release both the underlying pdfplumber page's internal layout
        cache AND this page's own cached `text`/`words`/`tables` (PAR-216)
        -- call after a page's data has been fully consumed inside a loop
        over many pages, so a 400+ page document doesn't retain every
        page's already-processed word list for the rest of the document's
        lifetime (this, combined with the eager-`text`-for-every-page issue
        `text` being made lazy above already fixes, was the direct cause of
        a real production OOM on a 451-page statement). Safe to call even
        mid-document: a later re-access of `.text`/`.words`/`.extract_tables()`
        on this page just recomputes from the underlying pdfplumber page
        (slower, not broken) rather than reusing a stale cache."""
        self._page.flush_cache()
        self._text = None
        self._words = None
        self._tables = None


class NormalizedDocument:
    """A single-parsed PDF. Holds the underlying pdfplumber.PDF open until
    `close()` (or context-manager exit) so lazily-accessed page data
    (`words`, `extract_tables()`) keeps working — callers that parse via
    `parse_pdf()` directly are responsible for closing it (use it as a
    context manager)."""

    def __init__(self, file_path: str, pdf: "pdfplumber.PDF"):
        self.file_path = file_path
        self._pdf = pdf
        self.pages: List[NormalizedPage] = [
            NormalizedPage(i, page) for i, page in enumerate(pdf.pages, start=1)
        ]

    def text_upto(self, n_pages: int) -> str:
        """Joined text of the first `n_pages` pages — the
        `" ".join(...)` pattern every `detect_*` function currently repeats
        with its own separate `pdfplumber.open()` call."""
        return " ".join(p.text for p in self.pages[:n_pages] if p.text)

    def close(self) -> None:
        self._pdf.close()

    def __enter__(self) -> "NormalizedDocument":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class PDFLockedError(Exception):
    """Raised by `parse_pdf()` when a PDF is encrypted and the supplied
    password (or the absence of one) doesn't open it.

    This is the one shared, bank-agnostic signal for "this file needs a
    password" (PAR-69). Every `detect_*`/`extract_*` function already
    routes through `parse_pdf()`/`as_document()`, so catching this in one
    place at the router/dispatch layer covers every current and future
    bank extractor — no per-bank password handling needed. NCBA's
    "e-Statement Of Account" template is the first caller; PAR-14 (Co-op
    Layout C) is expected to be the next.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        super().__init__(f"PDF is password-protected: {file_path}")


def parse_pdf(file_path: str, password: Optional[str] = None) -> NormalizedDocument:
    """Open the PDF exactly once and eagerly extract per-page text (cheap).
    Returns a `NormalizedDocument` — use as a context manager to guarantee
    the underlying file handle is closed.

    `password`, when given, is passed to pdfplumber for this open call
    only — never stored, logged, or reused across calls. Raises
    `PDFLockedError` if the file is encrypted and the password (or lack of
    one) doesn't unlock it; callers that want to prompt the analyst for a
    password should catch that specifically instead of treating it as a
    generic parse failure.
    """
    try:
        pdf = (
            pdfplumber.open(file_path, password=password)
            if password is not None
            else pdfplumber.open(file_path)
        )
    except PDFPasswordIncorrect as exc:
        raise PDFLockedError(file_path) from exc
    return NormalizedDocument(file_path, pdf)


@contextmanager
def as_document(source: Union[str, NormalizedDocument]) -> Iterator[NormalizedDocument]:
    """
    Accept either a file path or an already-parsed `NormalizedDocument`.

    Lets every `detect_*` function keep working unchanged for direct,
    single-file callers (existing tests all call `detect_kcb(path)` etc.
    directly) while `route_extract()` can pass its one shared, already-open
    `NormalizedDocument` through instead of triggering a fresh
    `pdfplumber.open()` per detector. Only opens (and only closes) a new
    document when given a bare path; reuses the caller's document as-is
    otherwise.
    """
    if isinstance(source, NormalizedDocument):
        yield source
        return
    doc = parse_pdf(source)
    try:
        yield doc
    finally:
        doc.close()
