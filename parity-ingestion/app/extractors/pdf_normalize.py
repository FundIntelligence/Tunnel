"""
Explicit, engine-independent PDF coordinate rotation normalization.

pdfplumber's extract_words()/extract_text() implicitly rotation-corrects
character positions before handing them back. Every bank extractor's
x-threshold column logic is calibrated against that implicit, undocumented
behavior (kcb_extractor.py:102 `_assign_kcb_column`, kcb_extractor.py's
`_KCB_ONLINE_*_X_MIN/MAX` constants near line 225, and the analogous
thresholds in equity_extractor.py around line 878).

pypdfium2 does not do this: `PdfTextPage.get_charbox()` returns raw,
pre-rotation coordinates in the page's original (un-rotated) coordinate
space (origin bottom-left, y increases upward). Confirmed via
rust_engine_prototype/investigation_pypdfium2_eval.md — a naive flip of
pdfium's raw boxes on this repo's rotated (90-degree) KCB fixture produces
negative, garbage positions (see that doc's section 5).

This module makes the rotation contract explicit and independently testable
(tests/test_pdf_normalize.py) so it holds regardless of which engine
produced the raw box: pdfplumber today (PAR-36), pypdfium2 tomorrow (PAR-37).
"""
from __future__ import annotations

from dataclasses import dataclass

_VALID_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class RawBox:
    """A box in a page's raw (pre-rotation) PDF coordinate space: origin
    bottom-left, y increases upward. This is what pypdfium2's
    ``PdfTextPage.get_charbox()`` returns, and what a PDF's content stream
    defines before any ``/Rotate`` is applied for display."""

    left: float
    bottom: float
    right: float
    top: float


@dataclass(frozen=True)
class UprightBox:
    """A box in the upright, rotation-corrected coordinate space every bank
    extractor's x-threshold logic is calibrated against: origin top-left,
    x increases right, ``top``/``bottom`` are distances down from the page's
    top edge as displayed. This matches pdfplumber's ``extract_words()``
    dict shape (``x0``, ``x1``, ``top``, ``bottom``)."""

    x0: float
    top: float
    x1: float
    bottom: float


def _rotate90_cw_raw(box: RawBox, width: float) -> RawBox:
    """
    Rotate a raw box 90 degrees clockwise, staying in raw (y-up,
    bottom-left-origin) coordinates. The frame this box lives in also
    rotates: its width becomes the old height and vice versa (the caller
    tracks that swap).

    Derived and verified against real pdfplumber output on this repo's
    90-degree-rotated KCB fixture (tests/test_pdf_normalize.py
    ``test_matches_pdfplumber_ground_truth_on_rotated_fixture``) — mapping
    the raw char box for the first letter of the word "Account" through this
    function (composed once, for rotation=90) reproduces pdfplumber's own
    upright word box to within font-metric rounding.
    """
    return RawBox(
        left=box.bottom,
        bottom=width - box.right,
        right=box.top,
        top=width - box.left,
    )


def normalize_box_rotation(
    box: RawBox, rotation: int, raw_width: float, raw_height: float
) -> UprightBox:
    """
    Map a raw (pre-rotation) PDF box to the upright, top-left-origin
    coordinate convention pdfplumber's ``extract_words()`` already applies
    implicitly, and that every bank extractor's x-threshold logic assumes.

    ``rotation`` is the page's ``/Rotate`` value in degrees clockwise (as
    reported by both pdfplumber's ``page.rotation`` and pypdfium2's
    ``PdfPage.get_rotation()``) — one of 0, 90, 180, 270.

    ``raw_width``/``raw_height`` are the page's un-rotated mediabox
    dimensions (pdfplumber's ``page.mediabox`` width/height — NOT
    ``page.width``/``page.height``, which are already display/rotation
    adjusted and swapped for 90/270).
    """
    rotation = rotation % 360
    if rotation not in _VALID_ROTATIONS:
        raise ValueError(f"Unsupported rotation: {rotation} (expected one of {_VALID_ROTATIONS})")

    width, height = raw_width, raw_height
    for _ in range(rotation // 90):
        box = _rotate90_cw_raw(box, width)
        width, height = height, width

    # `box` is now in the final (post-rotation) y-up frame, sized width x
    # height. Converting to top-down "distance from page top" is the same
    # step as the rotation=0 case, applied to whatever frame we ended up in.
    return UprightBox(
        x0=box.left,
        x1=box.right,
        top=height - box.top,
        bottom=height - box.bottom,
    )
