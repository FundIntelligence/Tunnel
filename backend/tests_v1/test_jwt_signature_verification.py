"""
JWT signature verification in the shared auth path (_extract_user_id_from_request).

Before this hardening the function base64-decoded the JWT payload and trusted
`sub` WITHOUT verifying the signature — any crafted token was accepted. It now
verifies the ES256 signature against the project's public JWKS, plus expiry and
audience. These tests prove the core new guarantee at two levels:

  1. The shared extractor directly: valid -> sub; forged/expired/missing/
     malformed/wrong-audience/unknown-kid -> None (rejected).
  2. End-to-end through the confirm endpoint: a forged token that previously
     would have populated `confirmed_by` with a spoofed sub is now rejected with
     401 CONFIRM_AUTH_REQUIRED, and nothing is written.

The signing keypair is throwaway and generated in-process; the API's JWKS fetch
is patched to return its public half (no network, no real secret).
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v1 import api as v1_api
from backend.v1.api import router as v1_router, _extract_user_id_from_request
from backend.v1.db.memory_repositories import build_memory_repos
from tests_v1.jwt_test_utils import (
    PUBLIC_JWKS,
    bearer,
    forged_bearer,
    make_token,
    make_forged_token,
    make_expired_token,
)


def _req(headers):
    """Minimal stand-in for fastapi.Request — only .headers is read."""
    return SimpleNamespace(headers=headers)


class TestExtractorVerification(unittest.TestCase):
    """Unit-level: the shared extractor returns a sub only for a valid token."""

    def setUp(self):
        p = patch("backend.v1.api._get_jwks", return_value=PUBLIC_JWKS)
        p.start()
        self.addCleanup(p.stop)

    def test_valid_token_returns_sub(self):
        tok = make_token("user-abc")
        self.assertEqual(
            _extract_user_id_from_request(_req({"authorization": f"Bearer {tok}"})),
            "user-abc",
        )

    def test_forged_signature_rejected(self):
        tok = make_forged_token("attacker-sub")
        self.assertIsNone(
            _extract_user_id_from_request(_req({"authorization": f"Bearer {tok}"})),
            "a token signed by an unpublished key must not be trusted",
        )

    def test_expired_token_rejected(self):
        tok = make_expired_token("user-abc")
        self.assertIsNone(
            _extract_user_id_from_request(_req({"authorization": f"Bearer {tok}"}))
        )

    def test_missing_header_returns_none(self):
        self.assertIsNone(_extract_user_id_from_request(_req({})))

    def test_non_bearer_scheme_returns_none(self):
        self.assertIsNone(
            _extract_user_id_from_request(_req({"authorization": "Basic abc123"}))
        )

    def test_malformed_token_rejected(self):
        self.assertIsNone(
            _extract_user_id_from_request(_req({"authorization": "Bearer not.a.jwt"}))
        )

    def test_wrong_audience_rejected(self):
        tok = make_token("user-abc", aud="some-other-service")
        self.assertIsNone(
            _extract_user_id_from_request(_req({"authorization": f"Bearer {tok}"})),
            "token minted for a different audience must be rejected",
        )

    def test_unknown_kid_rejected(self):
        # kid not present in the published JWKS -> no key to verify against.
        tok = make_token("user-abc", kid="some-unknown-kid")
        self.assertIsNone(
            _extract_user_id_from_request(_req({"authorization": f"Bearer {tok}"}))
        )

    def test_no_jwks_fails_closed(self):
        # If JWKS cannot be obtained, every token is rejected (never trust blind).
        tok = make_token("user-abc")
        with patch("backend.v1.api._get_jwks", return_value=None):
            self.assertIsNone(
                _extract_user_id_from_request(_req({"authorization": f"Bearer {tok}"}))
            )


_FY = 2025


class _FakeAFRepo:
    _store: dict = {}

    @classmethod
    def reset(cls):
        cls._store = {}

    def get_by_deal_year(self, deal_id, financial_year):
        row = self._store.get((deal_id, int(financial_year)))
        return row if row and row.get("removed_at") is None else None

    def get_by_deal_id(self, deal_id):
        return [r for (d, _fy), r in self._store.items()
                if d == deal_id and r.get("removed_at") is None]

    def upsert(self, data):
        key = (data["deal_id"], int(data["financial_year"]))
        merged = {**self._store.get(key, {}), **data}
        merged.setdefault("id", "af-row-1")
        self._store[key] = merged
        return merged


class _FakeConfirmLog:
    rows: list = []

    @classmethod
    def reset(cls):
        cls.rows = []

    def insert_log(self, entry):
        self.rows.append(entry)
        return entry


class TestConfirmEndpointRejectsForged(unittest.TestCase):
    """End-to-end: forged token can no longer populate confirmed_by."""

    def setUp(self):
        _FakeAFRepo.reset()
        _FakeConfirmLog.reset()
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        self._patches = [
            patch("backend.v1.db.supabase_repositories.AuditedFinancialsRepo", _FakeAFRepo),
            patch("backend.v1.db.supabase_repositories.AfConfirmLogRepo", _FakeConfirmLog),
            patch("backend.v1.api._get_jwks", return_value=PUBLIC_JWKS),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

        deal_resp = self.client.post("/v1/deals", data={"currency": "KES"})
        self.assertEqual(deal_resp.status_code, 200, deal_resp.text)
        self.deal_id = deal_resp.json()["deal"]["id"]

    def _confirm(self, headers):
        return self.client.patch(
            f"/v1/deals/{self.deal_id}/audited-financials/{_FY}",
            json={"turnover_cents": 5_000_00},
            headers=headers,
        )

    def test_valid_token_confirms(self):
        resp = self._confirm(bearer("real-user"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(_FakeAFRepo._store[(self.deal_id, _FY)]["confirmed_by"], "real-user")

    def test_forged_token_rejected_and_nothing_written(self):
        resp = self._confirm(forged_bearer("attacker-sub"))
        self.assertEqual(resp.status_code, 401, resp.text)
        self.assertEqual(resp.json()["detail"]["status"], "CONFIRM_AUTH_REQUIRED")
        self.assertNotIn((self.deal_id, _FY), _FakeAFRepo._store)
        self.assertEqual(_FakeConfirmLog.rows, [])


if __name__ == "__main__":
    unittest.main()
