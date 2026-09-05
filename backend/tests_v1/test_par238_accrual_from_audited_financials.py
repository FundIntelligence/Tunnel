"""
PAR-238 — reconciliation must read its accrual figures from the confirmed
pds_audited_financials record, not the disconnected deal.accrual_* fields.

Root cause: deal.accrual_revenue_cents/_period_start/_period_end are only
ever set once, as optional form fields on POST /deals at deal-creation time.
There is no update endpoint for them. PATCH /deals/{deal_id}/audited-
financials/{financial_year} — the actual "confirm financials" action — never
touches these deal fields at all. So a deal following the normal flow
(create deal, then upload/confirm audited financials afterward) was
structurally guaranteed to hit reconciliation_status == "NOT_RUN" forever,
no matter how complete the confirmed financials were.

Fix (Option B): the accrual={...} dict built at the run_pipeline() call site
in api.py's export() now reads AuditedFinancialsRepo.get_latest_confirmed()
instead of deal.get("accrual_*"). This test proves the fix end-to-end through
the real FastAPI route: a deal with NO deal.accrual_* fields ever set, but a
confirmed pds_audited_financials record and bank transactions whose declared-
vs-observed revenue and period line up, must produce a real (non-NOT_RUN)
reconciliation_status.

Style follows test_audited_financials_confirm_guard.py's established
convention: patch backend.v1.db.supabase_repositories.AuditedFinancialsRepo
with an in-memory stand-in rather than touching real Supabase, since the
endpoint code imports and instantiates the repo locally inside each function
(so patching the class at its module source is what the local `from ..db...
import AuditedFinancialsRepo` picks up).
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


class _FakeAFRepo:
    """In-memory stand-in for AuditedFinancialsRepo, sharing one store across
    every instantiation (the endpoint constructs its own instance per call).
    Only implements what PAR-238's call site needs: get_latest_confirmed."""

    _store: dict = {}

    @classmethod
    def reset(cls):
        cls._store = {}

    @classmethod
    def seed_confirmed(cls, deal_id, financial_year, **fields):
        cls._store[(deal_id, financial_year)] = {
            "deal_id": deal_id,
            "financial_year": financial_year,
            "confirmed_at": "2026-01-01T00:00:00Z",
            "removed_at": None,
            **fields,
        }

    def get_latest_confirmed(self, deal_id):
        candidates = [
            row for (d_id, _fy), row in self._store.items()
            if d_id == deal_id and row.get("confirmed_at") and not row.get("removed_at")
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.get("financial_year") or 0)

    def get_by_deal_id(self, deal_id):
        return [
            row for (d_id, _fy), row in self._store.items()
            if d_id == deal_id and not row.get("removed_at")
        ]

    def patch_coverage_summary(self, deal_id, financial_year, summary):
        key = (deal_id, financial_year)
        if key in self._store:
            self._store[key].update(summary)


# Two rows spanning the full declared accrual period exactly (2024-01-01 to
# 2024-01-31), so overlap_bp = 10000 (100%), well above the 60% threshold —
# isolates the test to "does the accrual data reach compute_metrics at all",
# not the overlap-threshold math (already covered elsewhere).
_REVENUE_CSV = (
    "date,amount,description,account_id\n"
    "2024-01-01,500.00,Sale to customer A,ACC-1\n"
    "2024-01-31,500.00,Sale to customer B,ACC-1\n"
)


class TestAccrualReadsFromConfirmedAuditedFinancials(unittest.TestCase):
    def setUp(self):
        _FakeAFRepo.reset()
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        self._patcher = patch(
            "backend.v1.db.supabase_repositories.AuditedFinancialsRepo",
            _FakeAFRepo,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        deal_resp = self.client.post("/v1/deals", data={"currency": "KES"})
        self.assertEqual(deal_resp.status_code, 200, deal_resp.text)
        self.deal_id = deal_resp.json()["deal"]["id"]

    def test_confirmed_audited_financials_drives_reconciliation_without_deal_accrual_fields(self):
        # No deal.accrual_* fields were ever set on this deal (POST /deals
        # above was called with only currency) — this is the exact scenario
        # PAR-238 describes: create deal, confirm financials afterward.
        deal = self.repos["deals"].get_deal(self.deal_id)
        self.assertIsNone(deal.get("accrual_revenue_cents"))
        self.assertIsNone(deal.get("accrual_period_start"))
        self.assertIsNone(deal.get("accrual_period_end"))

        # Bank data: two "Sale" transactions, KES 500.00 each -> KES 1,000.00
        # total revenue_operational inflow (100000 cents).
        f = io.BytesIO(_REVENUE_CSV.encode())
        up = self.client.post(
            f"/v1/deals/{self.deal_id}/documents",
            files={"file": ("statement.csv", f, "text/csv")},
        )
        self.assertEqual(up.status_code, 200, up.text)

        # Confirmed audited financials: declared turnover matches the bank
        # total exactly (diff=0), FY exactly spans the transaction dates.
        _FakeAFRepo.seed_confirmed(
            self.deal_id,
            2024,
            financial_year_start="2024-01-01",
            financial_year_end="2024-01-31",
            turnover_cents=100000,
        )

        resp = self.client.post(f"/v1/deals/{self.deal_id}/export")
        self.assertEqual(resp.status_code, 200, resp.text)
        run = resp.json()["analysis_run"]

        # The actual PAR-238 assertion: reconciliation ran at all.
        self.assertNotEqual(run["reconciliation_status"], "NOT_RUN")
        # Declared == observed exactly here, so it should be a clean OK,
        # not just "not NOT_RUN" — a stronger, more specific check.
        self.assertEqual(run["reconciliation_status"], "OK")

    def test_no_confirmed_audited_financials_still_not_run(self):
        # Sanity check for the "nothing set" branch PAR-238 says must not
        # change: no confirmed pds_audited_financials row at all (never
        # seeded here) behaves exactly like today's "nothing set" case.
        f = io.BytesIO(_REVENUE_CSV.encode())
        up = self.client.post(
            f"/v1/deals/{self.deal_id}/documents",
            files={"file": ("statement.csv", f, "text/csv")},
        )
        self.assertEqual(up.status_code, 200, up.text)

        resp = self.client.post(f"/v1/deals/{self.deal_id}/export")
        self.assertEqual(resp.status_code, 200, resp.text)
        run = resp.json()["analysis_run"]
        self.assertEqual(run["reconciliation_status"], "NOT_RUN")

    def test_unconfirmed_audited_financials_does_not_feed_reconciliation(self):
        # An unconfirmed record (confirmed_at IS NULL) must not be picked up —
        # this is the exact "UNCONFIRMED badge" scenario PAR-237's E2E test
        # hit, which PAR-238 explains was never going to work regardless of
        # confirmation status, and confirms it still correctly does not once
        # this fix is in place either, unless actually confirmed.
        f = io.BytesIO(_REVENUE_CSV.encode())
        up = self.client.post(
            f"/v1/deals/{self.deal_id}/documents",
            files={"file": ("statement.csv", f, "text/csv")},
        )
        self.assertEqual(up.status_code, 200, up.text)

        _FakeAFRepo._store[(self.deal_id, 2024)] = {
            "deal_id": self.deal_id,
            "financial_year": 2024,
            "financial_year_start": "2024-01-01",
            "financial_year_end": "2024-01-31",
            "turnover_cents": 100000,
            "confirmed_at": None,  # never confirmed
            "removed_at": None,
        }

        resp = self.client.post(f"/v1/deals/{self.deal_id}/export")
        self.assertEqual(resp.status_code, 200, resp.text)
        run = resp.json()["analysis_run"]
        self.assertEqual(run["reconciliation_status"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
