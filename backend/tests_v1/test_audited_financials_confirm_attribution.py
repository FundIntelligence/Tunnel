"""
Confirmation attribution: a confirm (PATCH "Save financial details") must record
WHO confirmed, durably.

  - with an authenticated user  -> 200; confirmed_by set on the row AND an
    append-only pds_af_confirm_log row written (who/when/FY).
  - without an identifiable user -> 401 CONFIRM_AUTH_REQUIRED; nothing confirmed,
    nothing logged.
  - legacy rows with null confirmed_by still read fine (GET) — old data is not
    retroactively attributed and must not error anywhere it is read.

Runs end-to-end through the real FastAPI routes; AuditedFinancialsRepo and
AfConfirmLogRepo are patched with in-memory fakes.
"""
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

_FY = 2025
_USER = "user-sub-abc123"


def _bearer(sub=_USER):
    """A genuinely signed ES256 token carrying `sub` (verifies against the
    patched test JWKS — see setUp)."""
    return bearer(sub)


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


class TestConfirmAttribution(unittest.TestCase):
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

    def _confirm(self, headers=None):
        return self.client.patch(
            f"/v1/deals/{self.deal_id}/audited-financials/{_FY}",
            json={"turnover_cents": 5_000_00},
            headers=headers or {},
        )

    def test_confirm_with_auth_sets_confirmed_by_and_logs(self):
        resp = self._confirm(headers=_bearer())
        self.assertEqual(resp.status_code, 200, resp.text)

        row = _FakeAFRepo._store[(self.deal_id, _FY)]
        self.assertEqual(row.get("confirmed_by"), _USER, "confirmed_by must be the JWT sub")
        self.assertIsNotNone(row.get("confirmed_at"), "confirmed_at must be stamped")

        self.assertEqual(len(_FakeConfirmLog.rows), 1, "exactly one audit row written")
        log = _FakeConfirmLog.rows[0]
        self.assertEqual(log["confirmed_by"], _USER)
        self.assertEqual(int(log["financial_year"]), _FY)
        self.assertEqual(log["deal_id"], self.deal_id)
        self.assertIsNotNone(log["confirmed_at"])

    def test_confirm_without_auth_rejected(self):
        resp = self._confirm(headers=None)
        self.assertEqual(resp.status_code, 401, resp.text)
        self.assertEqual(resp.json()["detail"]["status"], "CONFIRM_AUTH_REQUIRED")
        # Nothing confirmed, nothing logged.
        self.assertNotIn((self.deal_id, _FY), _FakeAFRepo._store)
        self.assertEqual(_FakeConfirmLog.rows, [])

    def test_legacy_null_confirmed_by_still_reads(self):
        # A row that predates confirmed_by (attribute simply absent / null).
        _FakeAFRepo._store[(self.deal_id, _FY)] = {
            "id": "legacy-1", "deal_id": self.deal_id, "financial_year": _FY,
            "confirmed_at": "2026-01-01T00:00:00+00:00", "confirmed_by": None,
            "removed_at": None,
        }
        resp = self.client.get(f"/v1/deals/{self.deal_id}/audited-financials")
        self.assertEqual(resp.status_code, 200, resp.text)
        records = resp.json()["records"]
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].get("confirmed_by"), "legacy row reads with null attribution")


if __name__ == "__main__":
    unittest.main()
