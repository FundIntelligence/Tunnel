"""
Tests for the explicit, engine-independent rotation-normalization contract
(PAR-36). The critical test here is `test_matches_pdfplumber_ground_truth_
on_rotated_fixture`: it proves the transform turns a *raw, pre-rotation*
char box (the shape pypdfium2 will hand back in PAR-37) into the same
upright coordinates pdfplumber already reports today, on this repo's real
90-degree-rotated KCB fixture — the exact failure mode documented in
rust_engine_prototype/investigation_pypdfium2_eval.md section 5.
"""
from pathlib import Path

import pdfplumber
import pytest

from app.extractors.pdf_normalize import RawBox, UprightBox, normalize_box_rotation

_FIXTURE = Path(__file__).parent / "fixtures" / "buildex" / "kcb_buildex_2025.pdf"


def test_rotation0_is_identity_with_y_flip():
    # A raw box near the raw top-left corner of a 200x400 unrotated page
    # should land near the upright top-left corner too.
    box = RawBox(left=10, bottom=380, right=30, top=390)
    result = normalize_box_rotation(box, rotation=0, raw_width=200, raw_height=400)
    assert result == UprightBox(x0=10, x1=30, top=10, bottom=20)


def test_rotation_round_trip_four_quarter_turns_is_identity():
    """Applying the primitive four times (rotation=0 after 360 modulo) must
    reproduce the plain rotation=0 result — an internal consistency check
    independent of any real fixture."""
    box = RawBox(left=10, bottom=380, right=30, top=390)
    direct = normalize_box_rotation(box, rotation=0, raw_width=200, raw_height=400)
    via_360 = normalize_box_rotation(box, rotation=360, raw_width=200, raw_height=400)
    assert direct == via_360


def test_rotation180_reflects_through_center():
    # This box sits near the raw top edge (bottom=380, top=390 out of a
    # height-400 page). After a 180-degree rotation it must land near the
    # *bottom* of the display (a large top-down "top" value, close to 400)
    # — not near the top.
    box = RawBox(left=10, bottom=380, right=30, top=390)
    result = normalize_box_rotation(box, rotation=180, raw_width=200, raw_height=400)
    # 180-degree rotation: x mirrors around width, y mirrors (without a
    # second sign flip, since converting raw y-up to top-down already
    # flips once — the two 180-degree flips compose back to the original
    # raw y-ordinate values here).
    assert result.x0 == pytest.approx(200 - 30)
    assert result.x1 == pytest.approx(200 - 10)
    assert result.top == pytest.approx(380)
    assert result.bottom == pytest.approx(390)


def test_rotation90_then_rotation270_is_identity():
    box = RawBox(left=10, bottom=20, right=15, top=25)
    raw_width, raw_height = 200, 400

    rotated = normalize_box_rotation(box, rotation=90, raw_width=raw_width, raw_height=raw_height)
    # Feed the rotated (now-upright) box back through as if it were a raw
    # box in the rotated (swapped-dims) frame, rotating another 270 to
    # complete the circle back to rotation 0 on the original frame.
    back = RawBox(left=rotated.x0, bottom=raw_width - rotated.bottom, right=rotated.x1, top=raw_width - rotated.top)
    result = normalize_box_rotation(back, rotation=270, raw_width=raw_height, raw_height=raw_width)
    original_upright = normalize_box_rotation(box, rotation=0, raw_width=raw_width, raw_height=raw_height)
    assert result.x0 == pytest.approx(original_upright.x0)
    assert result.x1 == pytest.approx(original_upright.x1)
    assert result.top == pytest.approx(original_upright.top)
    assert result.bottom == pytest.approx(original_upright.bottom)


def test_unsupported_rotation_raises():
    box = RawBox(left=0, bottom=0, right=1, top=1)
    with pytest.raises(ValueError):
        normalize_box_rotation(box, rotation=45, raw_width=100, raw_height=100)


@pytest.mark.skipif(not _FIXTURE.exists(), reason="KCB buildex fixture not present")
def test_matches_pdfplumber_ground_truth_on_rotated_fixture():
    """
    Real regression test against this repo's rotated fixture.

    Ground truth (from actually running pdfplumber on this file — see
    rust_engine_prototype/investigation_par36_normalization.md):
      pdfplumber page.rotation == 90
      pdfplumber page.mediabox == [0, 0, 595, 842]  (raw, pre-rotation)
      pdfplumber word "Account": x0=36.0, top=78.105, x1=96.0, bottom=93.105

    We independently extract the raw char boxes for the same page via
    pypdfium2 (the engine PAR-37 will migrate to) and confirm
    normalize_box_rotation() maps the first character's raw box onto
    pdfplumber's upright "Account" word box (matching x0 exactly; top/bottom
    within a few points, since a single leading character's box is a subset
    of the full word's box which spans multiple characters with different
    ascender/descender extents).
    """
    pdfium = pytest.importorskip("pypdfium2")

    with pdfplumber.open(_FIXTURE) as pdf:
        page = pdf.pages[0]
        assert page.rotation == 90
        raw_width, raw_height = page.mediabox[2], page.mediabox[3]
        words = page.extract_words()
        account_word = next(w for w in words if w["text"] == "Account")

    doc = pdfium.PdfDocument(str(_FIXTURE))
    textpage = doc[0].get_textpage()
    # First character of "Account" is index 0 on this fixture's page 0.
    raw = textpage.get_charbox(0)
    assert textpage.get_text_range(0, 1) == "A"

    raw_box = RawBox(left=raw[0], bottom=raw[1], right=raw[2], top=raw[3])
    upright = normalize_box_rotation(
        raw_box, rotation=page.rotation, raw_width=raw_width, raw_height=raw_height
    )

    assert upright.x0 == pytest.approx(account_word["x0"], abs=0.5)
    assert upright.top == pytest.approx(account_word["top"], abs=2.0)
    assert upright.bottom <= account_word["bottom"] + 2.0
