"""
Audited-financials record removal (soft-delete) — DELETE route behaviour.

Tiers, mirroring the 409 upload guard:
  • Unconfirmed record  -> removed freely (200 REMOVED, superseded=False)
  • Confirmed record    -> 409 CONFIRMED_RECORD_LOCKED unless ?supersede=true
  • Confirmed + supersede, no reason -> 422 SUPERSEDE_REASON_REQUIRED
  • Confirmed + supersede + reason    -> 200 REMOVED (superseded=True)
  • Removed record vanishes from the GET list (soft-delete, retained for audit)
  • Remove then re-upload the same FY re-activates the row
  • DELETE on an absent FY -> 404 RECORD_NOT_FOUND

Runs end-to-end through the real FastAPI routes in backend/v1/api.py; only the
extractor and the Supabase-backed AuditedFinancialsRepo are patched.
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
# Supabase JWT (verifies against the patched test JWKS in setUp).
_AUTH = bearer("test-user")


_FY = 2025


def _fake_extraction(file_bytes, file_name):
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
    """In-memory stand-in honouring the removed_at soft-delete semantics."""

    _store: dict = {}

    @classmethod
    def reset(cls):
        cls._store = {}

    def get_by_deal_year(self, deal_id, financial_year):
        row = self._store.get((deal_id, int(financial_year)))
        return row if row and row.get("removed_at") is None else None

    def get_by_deal_id(self, deal_id):
        return [
            r
            for (d, _fy), r in self._store.items()
            if d == deal_id and r.get("removed_at") is None
        ]

    def upsert(self, data):
        key = (data["deal_id"], int(data["financial_year"]))
        merged = {**self._store.get(key, {}), **data}
        merged.setdefault("id", "af-row-1")
        self._store[key] = merged
        return merged

    def soft_delete(self, deal_id, financial_year, removed_at, removed_reason, removed_by):
        row = self._store.get((deal_id, int(financial_year)))
        if not row or row.get("removed_at") is not None:
            return None
        row.update({
            "removed_at": removed_at,
            "removed_reason": removed_reason,
            "removed_by": removed_by,
        })
        return row


class TestAuditedFinancialsRemoval(unittest.TestCase):
    def setUp(self):
        _FakeAFRepo.reset()
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

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

    # ── helpers ──────────────────────────────────────────────────────────────
    def _upload(self):
        return self.client.post(
            f"/v1/deals/{self.deal_id}/upload-financials",
            files={"file": ("acme.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            data={"declaration_type": "audited"},
        )

    def _confirm(self):
        return self.client.patch(
            f"/v1/deals/{self.deal_id}/audited-financials/{_FY}",
            json={"turnover_cents": 5_000_00},
            headers=_AUTH,
        )

    def _remove(self, *, supersede=False, reason=None):
        url = f"/v1/deals/{self.deal_id}/audited-financials/{_FY}"
        if supersede:
            url += "?supersede=true"
        body = {"reason": reason} if reason is not None else {}
        return self.client.request("DELETE", url, json=body)

    def _list(self):
        r = self.client.get(f"/v1/deals/{self.deal_id}/audited-financials")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["records"]

    # ── tests ────────────────────────────────────────────────────────────────
    def test_unconfirmed_record_removed_freely(self):
        self.assertEqual(self._upload().status_code, 200)
        resp = self._remove()
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "REMOVED")
        self.assertFalse(body["superseded"])
        row = _FakeAFRepo._store[(self.deal_id, _FY)]
        self.assertIsNotNone(row["removed_at"])
        self.assertEqual(self._list(), [], "removed record must vanish from the queue")

    def test_confirmed_record_blocked_without_supersede(self):
        self.assertEqual(self._upload().status_code, 200)
        self.assertEqual(self._confirm().status_code, 200)
        resp = self._remove()
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["status"], "CONFIRMED_RECORD_LOCKED")
        # Row untouched — still active, still confirmed.
        row = _FakeAFRepo._store[(self.deal_id, _FY)]
        self.assertIsNone(row.get("removed_at"))
        self.assertIsNotNone(row.get("confirmed_at"))

    def test_confirmed_supersede_requires_reason(self):
        self.assertEqual(self._upload().status_code, 200)
        self.assertEqual(self._confirm().status_code, 200)
        resp = self._remove(supersede=True)
        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertEqual(resp.json()["detail"]["status"], "SUPERSEDE_REASON_REQUIRED")
        self.assertIsNone(_FakeAFRepo._store[(self.deal_id, _FY)].get("removed_at"))

    def test_confirmed_supersede_with_reason_succeeds(self):
        self.assertEqual(self._upload().status_code, 200)
        self.assertEqual(self._confirm().status_code, 200)
        resp = self._remove(supersede=True, reason="Uploaded to wrong deal")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "REMOVED")
        self.assertTrue(body["superseded"])
        row = _FakeAFRepo._store[(self.deal_id, _FY)]
        self.assertIsNotNone(row["removed_at"])
        self.assertEqual(row["removed_reason"], "Uploaded to wrong deal")
        self.assertEqual(self._list(), [])

    def test_remove_then_reupload_reactivates(self):
        self.assertEqual(self._upload().status_code, 200)
        self.assertEqual(self._remove().status_code, 200)
        self.assertEqual(self._list(), [])
        # Re-upload the same FY — the 409 guard skips the removed row and the
        # upsert clears removed_at, re-activating the record.
        self.assertEqual(self._upload().status_code, 200, "re-upload after removal allowed")
        records = self._list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["financial_year"], _FY)
        self.assertIsNone(records[0].get("removed_at"))

    def test_remove_absent_record_returns_404(self):
        resp = self._remove()
        self.assertEqual(resp.status_code, 404, resp.text)
        self.assertEqual(resp.json()["detail"]["status"], "RECORD_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
