"""
Regression test for PAR-77: a Review Queue resolution must survive a genuine
re-export (new document trigger), not just be preserved by the short-circuit
no-op path. Before this fix, run_pipeline reclassified every transaction from
scratch on each real re-export, silently discarding any analyst resolution
recorded in pds_override_log.
"""

import io
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v1.api import router as v1_router
from backend.v1.db.memory_repositories import build_memory_repos

# A large, unrecognized-description positive transaction lands in
# needs_review via the classifier's large-positive fallback (>= KES 100,000,
# no keyword match) — backend/v1/core/classifier.py:401.
DOC_1_CSV = """date,amount,description,account_id
2024-01-01,1000,Revenue,ACC-1
2024-01-02,-400,Supplier,ACC-1
2024-01-03,150000,Unrecognized Large Payment XYZ,ACC-1
"""

# Second document — triggers a genuine re-export (new document), not the
# short-circuit no-op path.
DOC_2_CSV = """date,amount,description,account_id
2024-02-01,2000,Revenue,ACC-1
2024-02-02,-500,Supplier,ACC-1
"""


class TestOverrideSurvivesReexport(unittest.TestCase):
    def setUp(self):
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        # export() instantiates AuditedFinancialsRepo directly (bypassing the
        # repos_factory pattern used everywhere else), which requires live
        # Supabase credentials this sandbox doesn't have — a pre-existing gap
        # unrelated to PAR-77 (test_export_short_circuit.py hits the same
        # wall). Mock it to return no audited financials, same as any deal
        # that hasn't uploaded them.
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

    def test_resolution_survives_genuine_reexport_via_new_document(self):
        deal_resp = self.client.post("/v1/deals", data={"currency": "USD"})
        self.assertEqual(deal_resp.status_code, 200)
        deal_id = deal_resp.json()["deal"]["id"]

        self._upload_and_wait(deal_id, DOC_1_CSV, "doc1.csv")

        # First export: establishes the needs_review flag on the large
        # unrecognized transaction.
        exp1 = self.client.post(f"/v1/deals/{deal_id}/export")
        self.assertEqual(exp1.status_code, 200)
        txn_map_1 = exp1.json()["txn_entity_map"]
        txn_count_before = len(txn_map_1)

        nr = self.client.get(f"/v1/deals/{deal_id}/transactions/needs-review")
        self.assertEqual(nr.status_code, 200)
        nr_body = nr.json()
        self.assertEqual(nr_body["total"], 1, "Exactly one transaction should be flagged needs_review")
        row_id = nr_body["transactions"][0]["row_id"]

        # Analyst resolves it.
        resolve = self.client.post(
            f"/v1/deals/{deal_id}/transactions/resolve",
            data={
                "row_id": row_id,
                "new_role": "revenue_non_operational",
                "analyst_initials": "AM",
                "reason_category": "known_exception",
                "reason_note": "",
            },
        )
        self.assertEqual(resolve.status_code, 200)
        self.assertEqual(resolve.json()["remaining_count"], 0)

        # Confirm resolved immediately (pre-re-export sanity check).
        nr_after_resolve = self.client.get(f"/v1/deals/{deal_id}/transactions/needs-review")
        self.assertEqual(nr_after_resolve.json()["total"], 0)

        # Upload a SECOND document — this is what triggers a genuine
        # re-export (new latest_doc_at bypasses the short-circuit), not the
        # force=True or no-op case.
        self._upload_and_wait(deal_id, DOC_2_CSV, "doc2.csv")

        exp2 = self.client.post(f"/v1/deals/{deal_id}/export")
        self.assertEqual(exp2.status_code, 200)
        txn_map_2 = exp2.json()["txn_entity_map"]

        # Transaction-count invariant (pipeline.py watched-path discipline):
        # the overlay must only patch the `role`/`role_version` fields on
        # matched rows — it must never add, drop, or duplicate txn_map rows.
        # Doc 2 adds 2 new transactions on top of doc 1's 3.
        self.assertEqual(txn_count_before, 3)
        self.assertEqual(len(txn_map_2), 5, "txn_map row count must reflect exactly all ingested transactions, no gain/loss from the overlay")

        resolved_rec = next((r for r in txn_map_2 if str(r.get("txn_id")) == str(row_id)), None)
        self.assertIsNotNone(resolved_rec, "Resolved transaction must still be present in txn_entity_map after re-export")
        self.assertEqual(
            resolved_rec["role"], "revenue_non_operational",
            "Resolved role must survive a genuine re-export (new document trigger), not revert to fresh classify() output"
        )
        self.assertEqual(
            resolved_rec.get("role_version"), "manual_override",
            "Overlaid rows must be tagged manual_override, distinguishing them from fresh v1_rules classification"
        )

        # PAR-77 side-effect fix: the Review Queue count must also reflect
        # the resolution surviving re-export, not just the role field.
        nr_final = self.client.get(f"/v1/deals/{deal_id}/transactions/needs-review")
        self.assertEqual(
            nr_final.json()["total"], 0,
            "Resolved item must stay off the needs_review count/list across a genuine re-export"
        )
        self.assertNotIn(
            row_id, [t["row_id"] for t in nr_final.json()["transactions"]],
            "Resolved transaction must not reappear in the needs_review list after re-export"
        )

    def test_unresolved_transactions_still_reclassify_normally(self):
        """The overlay must only affect transactions with a logged resolution —
        everything else keeps going through fresh classify() on every export."""
        deal_resp = self.client.post("/v1/deals", data={"currency": "USD"})
        deal_id = deal_resp.json()["deal"]["id"]

        self._upload_and_wait(deal_id, DOC_1_CSV, "doc1.csv")
        exp1 = self.client.post(f"/v1/deals/{deal_id}/export")
        txn_map_1 = {str(r["txn_id"]): r for r in exp1.json()["txn_entity_map"]}

        self._upload_and_wait(deal_id, DOC_2_CSV, "doc2.csv")
        exp2 = self.client.post(f"/v1/deals/{deal_id}/export")
        txn_map_2 = {str(r["txn_id"]): r for r in exp2.json()["txn_entity_map"]}

        # Every unresolved row from doc 1 must still carry the v1_rules
        # version tag (fresh classification), not manual_override.
        for txn_id, rec in txn_map_1.items():
            if rec.get("role") == "needs_review":
                continue  # this is the one we'd resolve in the other test
            self.assertEqual(
                txn_map_2[txn_id].get("role_version"), "v1_rules",
                f"Unresolved transaction {txn_id} must keep going through fresh classification"
            )


if __name__ == "__main__":
    unittest.main()
