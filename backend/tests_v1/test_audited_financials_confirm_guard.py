"""
Regression (Fix B): re-uploading audited financials over a human-CONFIRMED
record must be blocked with HTTP 409, never silently overwritten.

Flow exercised end-to-end through the real FastAPI routes:
  upload  -> 200 (row created, confirmed_at = NULL)
  confirm -> PATCH "Save financial details" stamps confirmed_at server-side
  upload  -> 409 CONFIRMED_RECORD_EXISTS (guard fires; no overwrite)

The extractor and the AuditedFinancialsRepo (Supabase-backed in production) are
patched; everything else runs through the genuine endpoint code in
backend/v1/api.py so the guard ordering is covered.
"""
import io
import os
import sys
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
from tests_v1.jwt_test_utils import PUBLIC_JWKS, bearer

# Confirming (PATCH) now requires an authenticated user with a genuinely signed
# Supabase JWT; this is one (verifies against the patched test JWKS in setUp).
_AUTH = bearer("test-user")


_FY = 2025


def _fake_extraction(file_bytes, file_name):
    """Stand-in for the production extractor — deterministic, no I/O."""
    return {
        "company_name": "Acme Ltd",
        "financial_year": _FY,
        "financial_year_start": "2025-01-01",
        "financial_year_end": "2025-12-31",
        "turnover_cents": 5_000_00,
        "total_expenses_cents": 3_000_00,
        "extraction_confidence": 88,
        "extraction_method": "fake_test",
    }


class _FakeAFRepo:
    """In-memory stand-in for AuditedFinancialsRepo sharing one store across
    every instantiation (the endpoint constructs its own instance)."""

    _store: dict = {}

    @classmethod
    def reset(cls):
        cls._store = {}

    def get_by_deal_year(self, deal_id, financial_year):
        return self._store.get((deal_id, int(financial_year)))

    def upsert(self, data):
        key = (data["deal_id"], int(data["financial_year"]))
        existing = self._store.get(key, {})
        merged = {**existing, **data}
        merged.setdefault("id", "af-row-1")
        self._store[key] = merged
        return merged


class TestConfirmedRecordUploadGuard(unittest.TestCase):
    def setUp(self):
        _FakeAFRepo.reset()
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        # Patch the extractor and the repo for the whole test.
        # NOTE (Phase 2): the ingestion hot path now calls the Claude extractor,
        # not extract_audited_financials_via_ingestion. Only the patch *target*
        # below changed to follow the new call site — every assertion in this
        # test (the Fix B 409 confirm-guard behaviour) is unchanged.
        self._patches = [
            patch(
                "backend.v1.parsing.audited_financials_claude_extractor.extract_audited_financials_claude",
                side_effect=_fake_extraction,
            ),
            patch(
                "backend.v1.db.supabase_repositories.AuditedFinancialsRepo",
                _FakeAFRepo,
            ),
            patch("backend.v1.api._get_jwks", return_value=PUBLIC_JWKS),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

        deal_resp = self.client.post("/v1/deals", data={"currency": "KES"})
        self.assertEqual(deal_resp.status_code, 200, deal_resp.text)
        self.deal_id = deal_resp.json()["deal"]["id"]

    def _upload(self):
        return self.client.post(
            f"/v1/deals/{self.deal_id}/upload-financials",
            files={"file": ("acme.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            data={"declaration_type": "audited"},
        )

    def test_upload_confirm_reupload_returns_409(self):
        # 1) First upload — creates an unconfirmed record.
        first = self._upload()
        self.assertEqual(first.status_code, 200, first.text)
        row = _FakeAFRepo._store[(self.deal_id, _FY)]
        self.assertIsNone(row.get("confirmed_at"), "fresh upload must be unconfirmed")

        # 2) Re-upload BEFORE confirming is still allowed (overwrites unconfirmed).
        second = self._upload()
        self.assertEqual(second.status_code, 200, "re-upload over unconfirmed is allowed")

        # 3) Confirm via the real "Save financial details" PATCH route.
        confirm = self.client.patch(
            f"/v1/deals/{self.deal_id}/audited-financials/{_FY}",
            json={"turnover_cents": 5_000_00},
            headers=_AUTH,
        )
        self.assertEqual(confirm.status_code, 200, confirm.text)
        self.assertIsNotNone(
            _FakeAFRepo._store[(self.deal_id, _FY)].get("confirmed_at"),
            "PATCH must stamp confirmed_at server-side",
        )

        # 4) Re-upload AFTER confirmation — must be blocked with 409.
        blocked = self._upload()
        self.assertEqual(blocked.status_code, 409, blocked.text)
        detail = blocked.json()["detail"]
        self.assertEqual(detail["status"], "CONFIRMED_RECORD_EXISTS")
        self.assertEqual(detail["financial_year"], _FY)
        self.assertIn("remove the existing record first", detail["detail"])

        # And the confirmed figures are untouched by the blocked upload.
        self.assertIsNotNone(_FakeAFRepo._store[(self.deal_id, _FY)].get("confirmed_at"))


if __name__ == "__main__":
    unittest.main()
