"""
Regression test for PAR-111: export()'s short-circuit freshness check only
ever read pds_overrides' latest timestamp, not pds_override_log's — so a
fresh Review Queue resolution (which writes to pds_override_log, not
pds_overrides) never invalidated the cache, and a plain re-export could
silently keep serving a pre-resolution snapshot instead of reaching
PIPELINE_START / export_persist_deal_state.

Investigation confirmed both tables are real and both matter: pds_overrides
is entity-level classification overrides fed into run_pipeline() (a separate
endpoint, POST /deals/{id}/overrides); pds_override_log is the per-transaction
resolve_transaction() audit trail, overlaid onto run_pipeline()'s output
afterward (PAR-77). The fix takes the max of both tables' latest timestamps.
"""

import io
import logging
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


class TestExportShortCircuitFreshness(unittest.TestCase):
    def setUp(self):
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        # Same pre-existing local-environment gap documented in
        # test_par77_override_survives_reexport.py — export() instantiates
        # AuditedFinancialsRepo directly, bypassing repos_factory.
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

    def test_resolve_then_export_reaches_pipeline_not_short_circuit(self):
        deal_resp = self.client.post("/v1/deals", data={"currency": "USD"})
        deal_id = deal_resp.json()["deal"]["id"]
        self._upload_and_wait(deal_id, DOC_1_CSV, "doc1.csv")

        # First export establishes a snapshot.
        exp1 = self.client.post(f"/v1/deals/{deal_id}/export")
        self.assertEqual(exp1.status_code, 200)

        # Immediate second export with nothing changed: control case — this
        # one SHOULD short-circuit. Proves the freshness check still works
        # for the genuine no-change case, not just "always re-run".
        with self.assertLogs("backend.v1.api", level="INFO") as control_logs:
            exp2 = self.client.post(f"/v1/deals/{deal_id}/export")
        self.assertEqual(exp2.status_code, 200)
        self.assertTrue(
            any("short_circuit=1" in m for m in control_logs.output),
            "Expected the unchanged re-export to short-circuit",
        )

        # Analyst resolves the flagged transaction — writes to pds_override_log.
        nr = self.client.get(f"/v1/deals/{deal_id}/transactions/needs-review")
        self.assertEqual(nr.json()["total"], 1)
        row_id = nr.json()["transactions"][0]["row_id"]
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

        # The bug: a plain export() right after a resolution used to still
        # short-circuit, because the freshness check never looked at
        # pds_override_log. With the fix, this must NOT short-circuit.
        with self.assertLogs("backend.v1.api", level="INFO") as post_resolve_logs:
            exp3 = self.client.post(f"/v1/deals/{deal_id}/export")
        self.assertEqual(exp3.status_code, 200)
        self.assertFalse(
            any("short_circuit=1" in m for m in post_resolve_logs.output),
            "PAR-111 regression: export() short-circuited right after a fresh "
            "Review Queue resolution instead of reaching the real pipeline",
        )
        # "PIPELINE_START" itself is only a local variable (used for exception
        # diagnostics), never logged directly — "PIPELINE_DONE" is logged right
        # after run_pipeline() returns, so it's the real observable proof the
        # pipeline actually ran rather than being short-circuited around.
        self.assertTrue(
            any("stage=PIPELINE_DONE" in m for m in post_resolve_logs.output),
            "Expected the post-resolution export to actually reach PIPELINE_DONE",
        )


if __name__ == "__main__":
    unittest.main()
