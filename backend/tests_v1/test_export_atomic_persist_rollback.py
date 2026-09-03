"""
Regression test for PAR-95: export()'s delete+reinsert of
pds_txn_entity_map/links/entities/pds_analysis_runs must be atomic.

Before this fix, those four tables were touched via four separate PostgREST
calls (three delete_eq + a four-call reinsert), so a failure partway through
the reinsert left pds_txn_entity_map (and links/entities) for the deal
genuinely EMPTY — indistinguishable from a deal with zero needs_review items
(PAR-93). This test forces a failure inside the reinsert half of the
sequence and confirms the failure is NOT observable as an empty table: the
deal's prior (pre-failed-export) data must still be present after the RPC
call raises, via a fresh re-read — not just that the exception propagates.
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

DOC_1_CSV = """date,amount,description,account_id
2024-01-01,1000,Revenue,ACC-1
2024-01-02,-400,Supplier,ACC-1
2024-01-03,150000,Unrecognized Large Payment XYZ,ACC-1
"""

# Second document — triggers a genuine re-export (new latest_doc_at bypasses
# the short-circuit), which is the code path that hits the delete+reinsert.
DOC_2_CSV = """date,amount,description,account_id
2024-02-01,2000,Revenue,ACC-1
2024-02-02,-500,Supplier,ACC-1
"""


class TestExportAtomicPersistRollback(unittest.TestCase):
    def setUp(self):
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        # export() instantiates AuditedFinancialsRepo directly (bypassing the
        # repos_factory pattern), which requires live Supabase credentials
        # this sandbox doesn't have — pre-existing gap, unrelated to PAR-95
        # (see test_par77_override_survives_reexport.py for the same mock).
        af_patcher = patch("backend.v1.db.supabase_repositories.AuditedFinancialsRepo")
        mock_af_cls = af_patcher.start()
        mock_af_cls.return_value.get_by_deal_id.return_value = []
        # PAR-238: export() now also calls get_latest_confirmed() to source
        # reconciliation's accrual figures — an unconfigured MagicMock here
        # would flow into compute_metrics() as accrual_revenue_cents and
        # blow up on `> 0`. None matches "no audited financials", same as
        # get_by_deal_id returning [] above.
        mock_af_cls.return_value.get_latest_confirmed.return_value = None
        self.addCleanup(af_patcher.stop)

    def _upload_and_wait(self, deal_id, csv_text, filename):
        up = self.client.post(
            f"/v1/deals/{deal_id}/documents",
            files={"file": (filename, io.BytesIO(csv_text.encode()), "text/csv")},
        )
        self.assertEqual(up.status_code, 200)
        doc_id = up.json()["ingestion"]["document_id"]
        status = self.client.get(f"/v1/documents/{doc_id}/status")
        self.assertEqual(status.json()["status"], "completed")
        return doc_id

    def test_forced_failure_mid_persist_rolls_back_deletes(self):
        deal_resp = self.client.post("/v1/deals", data={"currency": "USD"})
        self.assertEqual(deal_resp.status_code, 200)
        deal_id = deal_resp.json()["deal"]["id"]

        self._upload_and_wait(deal_id, DOC_1_CSV, "doc1.csv")

        exp1 = self.client.post(f"/v1/deals/{deal_id}/export")
        self.assertEqual(exp1.status_code, 200)

        txn_map_before = self.repos["txn_map"].list_by_deal(deal_id)
        links_before = self.repos["links"].list_by_deal(deal_id)
        entities_before = self.repos["entities"].list_by_deal(deal_id)
        self.assertTrue(txn_map_before, "precondition: first export must have persisted txn_map rows")

        self._upload_and_wait(deal_id, DOC_2_CSV, "doc2.csv")

        # Force a failure at the very last step of persist_deal_state — after
        # the deletes and after run/links/entities have been (re)written, but
        # before txn_map is upserted. In the old sequential-calls world this
        # exact failure point is what left pds_txn_entity_map permanently
        # empty; the RPC's single-transaction semantics must undo everything,
        # not just this last step.
        def failing_upsert_mappings(*args, **kwargs):
            raise RuntimeError("simulated failure inside export_persist_deal_state")

        # TestClient defaults to raise_server_exceptions=True, so an
        # unhandled exception from the route handler propagates here as a
        # Python exception rather than an HTTP 500 response — export()'s
        # `raise` (after the critical log) is exactly that.
        with patch.object(self.repos["txn_map"], "upsert_mappings", side_effect=failing_upsert_mappings):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/v1/deals/{deal_id}/export")

        # Re-read (not the same objects held above) to confirm the deal's
        # prior state survived the failed export, instead of being wiped by
        # the deletes with no successful reinsert behind them.
        txn_map_after = self.repos["txn_map"].list_by_deal(deal_id)
        links_after = self.repos["links"].list_by_deal(deal_id)
        entities_after = self.repos["entities"].list_by_deal(deal_id)

        self.assertTrue(
            txn_map_after,
            "pds_txn_entity_map must not be empty after a failed export — "
            "this is the exact PAR-93 data-integrity gap PAR-95 closes",
        )
        self.assertEqual(
            {r["txn_id"] for r in txn_map_after},
            {r["txn_id"] for r in txn_map_before},
            "txn_map must be rolled back to its pre-failed-export state, not partially applied",
        )
        self.assertEqual(len(links_after), len(links_before))
        self.assertTrue(entities_after)
        self.assertEqual(
            {e["entity_id"] for e in entities_after},
            {e["entity_id"] for e in entities_before},
        )

        # The Review Queue read that PAR-93 called out explicitly: it must
        # not read "0 remaining" as if the deal were genuinely clean.
        nr = self.client.get(f"/v1/deals/{deal_id}/transactions/needs-review")
        self.assertEqual(nr.status_code, 200)
        # Same needs_review rows as before the failed export — not wiped.
        before_ids = {m["txn_id"] for m in txn_map_before if (m.get("role") or "") == "needs_review"}
        after_ids = {t["row_id"] for t in nr.json()["transactions"]}
        self.assertEqual(after_ids, before_ids)


if __name__ == "__main__":
    unittest.main()
