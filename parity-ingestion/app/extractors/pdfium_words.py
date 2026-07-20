"""
pypdfium2-based word extraction (PAR-37).

pypdfium2 has no word-level API — only per-character boxes
(`PdfTextPage.get_charbox()`), in the page's raw, pre-rotation coordinate
space. This module reimplements pdfplumber's `extract_words()` contract on
top of that: group characters into words using the same
whitespace-plus-tolerance heuristic pdfplumber uses, and normalize every
char's raw box through `app.extractors.pdf_normalize.normalize_box_rotation`
(built and independently verified in PAR-36) before grouping, so the output
shape and coordinate convention is a drop-in match for pdfplumber's word
dicts: ``{text, x0, x1, top, bottom}``.

Confirmed ~4.6-5.0x faster than pdfplumber's `extract_words()` on the 126-page
rotated KCB fixture (rust_engine_prototype/investigation_pypdfium2_eval.md).
This module is the "safe to ship" half of that finding: every bank
extractor's x-threshold column logic is calibrated against pdfplumber's
upright word coordinates, so word grouping + rotation correctness here is
tested directly against real pdfplumber output on the same rotated fixture
(tests/test_pdfium_words.py), not just benchmarked for speed.
"""
from __future__ import annotations

from collections import defaultdict
from typing import List, TypedDict

import pypdfium2 as pdfium

from app.extractors.pdf_document import WORD_Y_TOLERANCE
from app.extractors.pdf_normalize import RawBox, UprightBox, normalize_box_rotation

# pdfplumber's own WORD_X_TOLERANCE (3, see pdf_document.py) is calibrated
# against pdfplumber's own glyph-width measurements. pypdfium2 measures
# glyph boxes with slightly different metrics for the same font/rendering —
# on the real KCB Online fixture, the gap between the last digit of a date
# and its following "." is 3.01pt under pypdfium2 but the two are clearly
# meant to be one token ("30.01.2025", confirmed as a single pdfplumber word
# at the same position). A small explicit widening compensates for that
# cross-engine measurement drift without materially risking false merges
# (verified: this fixture's date-token count matches pdfplumber's exactly at
# this tolerance — tests/test_pdfium_words.py).
PDFIUM_X_TOLERANCE = 3.5

_WHITESPACE = {" ", "\t", "\r", "\n", "\x00"}


class Word(TypedDict):
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


class _WordBuilder:
    __slots__ = ("chars", "box")

    def __init__(self) -> None:
        self.chars: List[str] = []
        self.box: UprightBox | None = None

    def add(self, ch: str, box: UprightBox) -> None:
        self.chars.append(ch)
        if self.box is None:
            self.box = box
        else:
            self.box = UprightBox(
                x0=min(self.box.x0, box.x0),
                x1=max(self.box.x1, box.x1),
                top=min(self.box.top, box.top),
                bottom=max(self.box.bottom, box.bottom),
            )

    def finalize(self) -> Word:
        assert self.box is not None
        return Word(
            text="".join(self.chars),
            x0=self.box.x0,
            x1=self.box.x1,
            top=self.box.top,
            bottom=self.box.bottom,
        )


def _group_chars_into_words(
    chars: List[str],
    boxes: List[UprightBox],
    x_tolerance: float,
    y_tolerance: float,
) -> List[Word]:
    """
    Group a page's characters (already rotation-normalized, in reading
    order) into words: a run of non-whitespace characters on the same line
    with consecutive horizontal gaps no larger than `x_tolerance`. Mirrors
    pdfplumber's `extract_words()` grouping semantics closely enough to
    reproduce its word boundaries on real bank-statement layouts (verified
    in tests/test_pdfium_words.py against the real rotated KCB fixture).

    Line membership is a *vertical-interval-overlap* test against the
    current word's accumulated box, not a point comparison against the
    previous character's `top`. Punctuation (e.g. ``.`` in a date like
    "30.01.2025") sits low in its glyph cell with no ascender — its `top`
    can differ from a neighboring digit's `top` by several points even
    though both clearly belong to the same visual line. A period's small
    box is fully contained within the digits' taller box, so an interval
    test (do the two vertical ranges overlap, within `y_tolerance`?)
    correctly keeps them in one word where a `top`-to-`top` distance check
    would incorrectly split the date apart.
    """
    words: List[Word] = []
    current: _WordBuilder | None = None
    prev_x1: float | None = None

    for ch, box in zip(chars, boxes):
        if ch in _WHITESPACE or ch == "":
            if current is not None:
                words.append(current.finalize())
                current = None
            prev_x1 = None
            continue

        same_word = False
        if current is not None and prev_x1 is not None:
            word_box = current.box
            same_line = (
                box.top <= word_box.bottom + y_tolerance
                and box.bottom >= word_box.top - y_tolerance
            )
            gap = box.x0 - prev_x1
            same_word = same_line and gap <= x_tolerance

        if not same_word:
            if current is not None:
                words.append(current.finalize())
            current = _WordBuilder()

        current.add(ch, box)
        prev_x1 = box.x1

    if current is not None:
        words.append(current.finalize())

    return _normalize_line_boxes(words, y_tolerance)


def _normalize_line_boxes(words: List[Word], y_tolerance: float) -> List[Word]:
    """
    Give every word on the same visual line an identical top/bottom (the
    line's own union bbox), matching pdfplumber's `extract_words()`
    behavior: pdfplumber's words on one row all share the same top/bottom
    (confirmed by inspecting real ground truth — e.g. "Outward"/"SWIFT"/"P"/
    "LAMINATED" all report `top=40.277000000000044` on the KCB Online
    fixture). This module computes each word's box from only its own
    characters, so two words on the same line can end up with slightly
    different top/bottom (a word with no tall ascenders sits marginally
    lower than one that has some). Left unnormalized, that breaks any
    downstream `sorted(words, key=lambda w: (w["top"], w["x0"]))` — the
    ordering pdfplumber's near-identical tops make free, this makes
    explicit and enforced.

    Line clustering here uses the same fixed-grid bucket-rounding approach
    as this codebase's own `app.extractors.shared._group_by_line` — each
    word's bucket is computed independently from its own `top` (rounded to
    the nearest `y_tolerance`-wide grid line), not from a running/expanding
    window. An expanding-interval-overlap merge was tried first and
    rejected: on dense multi-line description blocks it cascaded — merging
    two genuinely-adjacent lines could grow the running box just enough to
    then swallow a third, unrelated line, scrambling word order far worse
    than doing nothing. Fixed-grid bucketing cannot cascade since bucket
    boundaries don't move.
    """
    if not words:
        return words

    buckets: dict = defaultdict(list)
    for i, w in enumerate(words):
        bucket_key = round(w["top"] / y_tolerance) * y_tolerance
        buckets[bucket_key].append(i)

    normalized = list(words)
    for indices in buckets.values():
        top = min(words[i]["top"] for i in indices)
        bottom = max(words[i]["bottom"] for i in indices)
        for i in indices:
            w = words[i]
            normalized[i] = Word(text=w["text"], x0=w["x0"], x1=w["x1"], top=top, bottom=bottom)

    return normalized


def extract_words_pdfium_page(
    page: "pdfium.PdfPage",
    x_tolerance: float = PDFIUM_X_TOLERANCE,
    y_tolerance: float = WORD_Y_TOLERANCE,
) -> List[Word]:
    """Extract upright, pdfplumber-shaped word dicts from one pypdfium2 page."""
    rotation = page.get_rotation()
    mediabox = page.get_mediabox()
    raw_width = mediabox[2] - mediabox[0]
    raw_height = mediabox[3] - mediabox[1]

    textpage = page.get_textpage()
    n = textpage.count_chars()

    chars: List[str] = []
    boxes: List[UprightBox] = []
    for i in range(n):
        ch = textpage.get_text_range(i, 1)
        left, bottom, right, top = textpage.get_charbox(i)
        raw_box = RawBox(left=left, bottom=bottom, right=right, top=top)
        upright = normalize_box_rotation(raw_box, rotation, raw_width, raw_height)
        chars.append(ch)
        boxes.append(upright)

    return _group_chars_into_words(chars, boxes, x_tolerance, y_tolerance)


def extract_words_pdfium(
    file_path: str,
    x_tolerance: float = PDFIUM_X_TOLERANCE,
    y_tolerance: float = WORD_Y_TOLERANCE,
) -> List[List[Word]]:
    """Extract upright, pdfplumber-shaped word dicts for every page of a PDF,
    via pypdfium2. Returns one list of words per page."""
    doc = pdfium.PdfDocument(file_path)
    try:
        return [
            extract_words_pdfium_page(doc[i], x_tolerance, y_tolerance)
            for i in range(len(doc))
        ]
    finally:
        doc.close()
