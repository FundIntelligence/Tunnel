"""Tests for the generic, bank-agnostic password wiring in the router
(PAR-69).

This is deliberately not NCBA-specific: it tests `route_extract()`'s shared
locked-PDF handling (`PDFLockedError` -> PASSWORD_REQUIRED/PASSWORD_INCORRECT)
and the security invariant that a supplied password never ends up anywhere
in the extraction record. NCBA's "e-Statement Of Account" template is used
here only because it's the first real locked-PDF fixture available — the
mechanism under test lives in `pdf_document.py`/`router.py`, not in
`ncba_extractor.py`.

Fixtures referenced directly from the real-samples client tree (gitignored,
never committed), same convention as test_ncba_estatement.py. Skipped
gracefully if absent.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.extractors.router import (
    route_extract,
    PASSWORD_REQUIRED_RESPONSE,
    PASSWORD_INCORRECT_RESPONSE,
)
from app.extractors.pdf_document import PDFLockedError, parse_pdf

FIXTURE_DIR = (
    "tests/fixtures/real_samples/clients/sayuni/Finalleg/"
    "re_parity_x_sayuni_pilot_12/Bank Statements/NCBA"
)
PASSWORD_FILE = f"{FIXTURE_DIR}/NCBA Password.txt"
JAN_2024 = f"{FIXTURE_DIR}/NCBA_2024/NCBA_Jan2024.pdf"

_KCB_BUILDEX = (
    pathlib.Path(__file__).parent / "fixtures" / "buildex" / "kcb_buildex_2025.pdf"
)


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


pytestmark = pytest.mark.skipif(
    not _can_open(JAN_2024, FIXTURE_PASSWORD),
    reason="NCBA e-statement fixture or password file missing/unreadable",
)


class TestSharedLockedPdfDetection:
    """Generic step, exercised at the pdf_document.py layer directly —
    nothing here is NCBA-aware."""

    def test_parse_pdf_raises_locked_error_without_password(self):
        with pytest.raises(PDFLockedError):
            parse_pdf(JAN_2024)

    def test_parse_pdf_raises_locked_error_with_wrong_password(self):
        with pytest.raises(PDFLockedError):
            parse_pdf(JAN_2024, password="wrong-password")

    def test_parse_pdf_succeeds_with_correct_password(self):
        with parse_pdf(JAN_2024, password=FIXTURE_PASSWORD) as doc:
            assert doc.pages


class TestRoutePasswordSignals:
    def test_no_password_returns_password_required(self):
        result = route_extract(JAN_2024)
        assert result == PASSWORD_REQUIRED_RESPONSE

    def test_wrong_password_returns_password_incorrect(self):
        result = route_extract(JAN_2024, password="wrong-password")
        assert result == PASSWORD_INCORRECT_RESPONSE

    def test_correct_password_extracts_successfully(self):
        result = route_extract(JAN_2024, password=FIXTURE_PASSWORD)
        assert not isinstance(result, dict)
        assert result.extractor_type == "ncba_estatement_pdf"
        assert result.row_count == 140

    def test_password_not_cached_between_calls(self):
        """A correct password on one call must not leak into a later call
        for the same file that omits it — per-request only, no caching."""
        ok = route_extract(JAN_2024, password=FIXTURE_PASSWORD)
        assert not isinstance(ok, dict)

        again = route_extract(JAN_2024)
        assert again == PASSWORD_REQUIRED_RESPONSE


class TestPasswordNeverPersistedInResult:
    def test_password_absent_from_serialized_extraction_result(self):
        result = route_extract(JAN_2024, password=FIXTURE_PASSWORD)
        assert not isinstance(result, dict)

        dumped = result.model_dump_json()
        assert FIXTURE_PASSWORD not in dumped

    def test_password_absent_from_raw_transactions_repr(self):
        result = route_extract(JAN_2024, password=FIXTURE_PASSWORD)
        assert not isinstance(result, dict)

        for t in result.raw_transactions:
            assert FIXTURE_PASSWORD not in repr(t)
            assert FIXTURE_PASSWORD not in t.description
            assert FIXTURE_PASSWORD not in (t.source_file or "")

    def test_password_absent_from_warnings(self):
        result = route_extract(JAN_2024, password=FIXTURE_PASSWORD)
        assert not isinstance(result, dict)

        for w in result.warnings:
            assert FIXTURE_PASSWORD not in repr(w)


class TestNonLockedParserPathUnaffected:
    """Regression guard: adding the password kwarg must not change behavior
    for the overwhelming majority of files, which aren't encrypted at all."""

    @pytest.mark.skipif(not _KCB_BUILDEX.exists(), reason="KCB buildex fixture not present")
    def test_kcb_still_routes_normally_with_no_password_arg(self):
        result = route_extract(str(_KCB_BUILDEX))
        assert not isinstance(result, dict) or result.get("status") != "UNSUPPORTED_FORMAT"
        if hasattr(result, "extractor_type"):
            assert result.extractor_type == "kcb_online_pdf"

    @pytest.mark.skipif(not _KCB_BUILDEX.exists(), reason="KCB buildex fixture not present")
    def test_kcb_still_routes_normally_with_explicit_none_password(self):
        result = route_extract(str(_KCB_BUILDEX), password=None)
        assert not isinstance(result, dict) or result.get("status") != "UNSUPPORTED_FORMAT"


class TestUploadEndpointPasswordHandling:
    """HTTP-layer check for /v1/ingest/upload's password field. Also guards
    against the pre-existing bug this change fixed in main.py: an
    HTTPException raised for a known status (415/401) was being caught by
    the endpoint's own broad `except Exception` and flattened into a
    generic 500 before it ever reached the client."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_locked_pdf_without_password_returns_401_not_500(self, client):
        with open(JAN_2024, "rb") as f:
            resp = client.post(
                "/v1/ingest/upload",
                files={"file": ("statement.pdf", f, "application/pdf")},
            )
        assert resp.status_code == 401
        assert "password" in resp.json()["detail"].lower()

    def test_locked_pdf_wrong_password_returns_401_not_500(self, client):
        with open(JAN_2024, "rb") as f:
            resp = client.post(
                "/v1/ingest/upload",
                files={"file": ("statement.pdf", f, "application/pdf")},
                data={"password": "wrong-password"},
            )
        assert resp.status_code == 401

    def test_locked_pdf_correct_password_extracts_and_response_omits_password(self, client):
        with open(JAN_2024, "rb") as f:
            resp = client.post(
                "/v1/ingest/upload",
                files={"file": ("statement.pdf", f, "application/pdf")},
                data={"password": FIXTURE_PASSWORD},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["extractor_type"] == "ncba_estatement_pdf"
        assert FIXTURE_PASSWORD not in resp.text
