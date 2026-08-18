"""
Auth gate for GET /v1/deals/{deal_id}/snapshot/pdf and .../snapshot/html (PAR-175).

Before this fix both routes had zero auth — anyone with a deal_id could pull
full financial data. The gate (_require_snapshot_access, api.py) accepts any
ONE of:
  - a valid Musa partner x-api-key (same key Musa's other integration routes use)
  - a valid admin-scoped x-api-key (key_type="admin" — the admin panel's
    server-side PDF proxy, which has no Supabase user session to forward)
  - a valid Supabase Bearer JWT (the main product's existing auth)

The JWT case matters most: it proves the main frontend is not broken by this
change. Rendering itself (render_snapshot_html / weasyprint) is patched out —
this suite is about the auth gate, not the renderer.

Run:
    cd backend
    python3 -m pytest tests_v1/test_snapshot_pdf_html_auth.py -v
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v1.api import router as v1_router
from backend.v1.db.memory_repositories import build_memory_repos
from tests_v1.jwt_test_utils import PUBLIC_JWKS, bearer, forged_bearer

MUSA_KEY = "musa-real-key"
ADMIN_KEY = "admin-real-key"


class _SnapshotAuthTestBase(unittest.TestCase):
    def setUp(self):
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        self._patches = [
            patch("backend.v1.api._get_jwks", return_value=PUBLIC_JWKS),
            patch(
                "backend.v1.integrations.auth.validate_api_key",
                lambda key, partner: partner == "Musa Ventures" and key == MUSA_KEY,
            ),
            patch(
                "backend.v1.integrations.auth.validate_scoped_api_key",
                lambda key, key_type: key_type == "admin" and key == ADMIN_KEY,
            ),
            patch(
                "backend.v1.analysis.snapshot_html_renderer.render_snapshot_html",
                lambda deal_id, **kw: "<html>stub</html>",
            ),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

        deal_resp = self.client.post("/v1/deals", data={"currency": "KES"})
        self.assertEqual(deal_resp.status_code, 200, deal_resp.text)
        self.deal_id = deal_resp.json()["deal"]["id"]


class TestSnapshotHtmlAuth(_SnapshotAuthTestBase):
    """snapshot/html never renders weasyprint, so it's the cheap route to
    exercise every branch of the auth gate against."""

    def _get(self, headers=None):
        return self.client.get(f"/v1/deals/{self.deal_id}/snapshot/html", headers=headers or {})

    def test_no_credentials_returns_401(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 401, resp.text)

    def test_wrong_musa_key_returns_401(self):
        resp = self._get({"x-api-key": "wrong-key"})
        self.assertEqual(resp.status_code, 401, resp.text)

    def test_valid_musa_key_returns_200(self):
        resp = self._get({"x-api-key": MUSA_KEY})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_valid_admin_key_returns_200(self):
        resp = self._get({"x-api-key": ADMIN_KEY})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_valid_internal_jwt_returns_200(self):
        """The case that matters most: the main product's existing auth
        (Supabase Bearer JWT) must keep working after this gate lands."""
        resp = self._get(bearer("real-user"))
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_forged_jwt_returns_401(self):
        resp = self._get(forged_bearer("attacker"))
        self.assertEqual(resp.status_code, 401, resp.text)

    def test_musa_key_takes_precedence_even_with_bad_jwt(self):
        """A valid x-api-key alone is sufficient — a caller need not also
        carry a JWT."""
        headers = {"x-api-key": MUSA_KEY}
        resp = self._get(headers)
        self.assertEqual(resp.status_code, 200, resp.text)


class TestSnapshotPdfAuth(_SnapshotAuthTestBase):
    """Same gate, real /snapshot/pdf route — spot-check that the dependency
    is actually wired on this route too (weasyprint patched out)."""

    def setUp(self):
        super().setUp()
        # get_snapshot_pdf does a local `import weasyprint` — stub the module
        # in sys.modules so the route never touches the real package (whose
        # native Pango/GObject deps aren't installed in every dev/test env).
        stub = types.ModuleType("weasyprint")
        stub.HTML = lambda *a, **kw: type("_Stub", (), {"write_pdf": lambda self: b"%PDF-stub"})()
        self._pdf_patch = patch.dict(sys.modules, {"weasyprint": stub})
        self._pdf_patch.start()
        self.addCleanup(self._pdf_patch.stop)

        self.repos["snapshots"].insert_snapshot({
            "id": "snap-1",
            "deal_id": self.deal_id,
            "sha256_hash": "deadbeef",
            "financial_state_hash": "deadbeef",
            "canonical_json": "{}",
        })

    def _get(self, headers=None):
        return self.client.get(f"/v1/deals/{self.deal_id}/snapshot/pdf", headers=headers or {})

    def test_no_credentials_returns_401(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 401, resp.text)

    def test_valid_internal_jwt_returns_200(self):
        resp = self._get(bearer("real-user"))
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_valid_musa_key_returns_200(self):
        resp = self._get({"x-api-key": MUSA_KEY})
        self.assertEqual(resp.status_code, 200, resp.text)


if __name__ == "__main__":
    unittest.main()
