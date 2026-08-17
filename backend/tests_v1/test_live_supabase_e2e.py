"""
Live E2E smoke test against Supabase.

Skipped unless **all** of these env vars are set:
    SUPABASE_TEST_MODE=1
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

When enabled the test creates real rows in the remote database, validates
immutability triggers + dual-hash semantics, then cleans up after itself.

Run:
    SUPABASE_TEST_MODE=1 \
    SUPABASE_URL=https://xxx.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=eyJ... \
    python3 -m pytest backend/tests_v1/test_live_supabase_e2e.py -v
"""

import hashlib
import json
import os
import sys
import time
import unittest
import uuid
from typing import Any, Dict, Optional

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.v1.core.pipeline import run_pipeline
from backend.v1.core.snapshot_engine import build_pds_payload, export_snapshot
from backend.v1.parsing.common import canonical_hash, normalize_descriptor

# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

_SUPABASE_TEST_MODE = os.getenv("SUPABASE_TEST_MODE", "") == "1"
_URL = os.getenv("SUPABASE_URL")
_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
_ENABLED = _SUPABASE_TEST_MODE and bool(_URL) and bool(_KEY)

_skip_reason = (
    "Supabase live E2E disabled — set SUPABASE_TEST_MODE=1, "
    "SUPABASE_URL, and SUPABASE_SERVICE_ROLE_KEY to enable"
)


def _sb():
    from supabase import create_client
    return create_client(_URL, _KEY)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _txn(date: str, cents: int, desc: str, account: str, document_id: str, deal_id: str) -> Dict[str, Any]:
    norm = normalize_descriptor(desc)
    txn_id = hashlib.sha256(
        f"{document_id}|{account}|{date}|{cents}|{norm}".encode()
    ).hexdigest()
    return {
        "id": str(uuid.uuid4()),
        "deal_id": deal_id,
        "document_id": document_id,
        "account_id": account,
        "txn_date": date,
        "signed_amount_cents": cents,
        "raw_descriptor": desc,
        "parsed_descriptor": desc.strip(),
        "normalized_descriptor": norm,
        "txn_id": txn_id,
        "is_transfer": False,
    }


# ---------------------------------------------------------------------------
# Supabase-backed repository adapter (thin, for this test only)
# ---------------------------------------------------------------------------

class _SBSnapshotRepo:
    """Minimal snapshot repository wired to the live Supabase pds_snapshots table."""
    def __init__(self, client):
        self._c = client

    def get_by_hash(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        res = self._c.table("pds_snapshots").select("*").eq("sha256_hash", sha256_hash).execute()
        return res.data[0] if res.data else None

    def insert_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.get_by_hash(snapshot.get("sha256_hash"))
        if existing:
            return existing
        res = self._c.table("pds_snapshots").insert(snapshot).execute()
        return res.data[0] if res.data else snapshot

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        res = self._c.table("pds_snapshots").select("*").eq("id", snapshot_id).execute()
        return res.data[0] if res.data else None

    def list_snapshots(self, deal_id: str):
        res = self._c.table("pds_snapshots").select("*").eq("deal_id", deal_id).execute()
        return res.data or []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(_ENABLED, _skip_reason)
class TestLiveSupabaseE2E(unittest.TestCase):
    """Full deal→ingest→export→override→revert against live Supabase."""

    @classmethod
    def setUpClass(cls):
        cls.sb = _sb()
        cls.created_by = str(uuid.uuid4())
        cls.deal_id = str(uuid.uuid4())
        cls.doc_id = str(uuid.uuid4())
        cls.analysis_run_ids = []
        cls.snapshot_ids = []

        # Create deal
        cls.sb.table("pds_deals").insert({
            "id": cls.deal_id,
            "currency": "USD",
            "name": "E2E Smoke Test",
            "created_by": cls.created_by,
        }).execute()

        # Create document
        cls.sb.table("pds_documents").insert({
            "id": cls.doc_id,
            "deal_id": cls.deal_id,
            "storage_url": "inline://e2e.csv",
            "file_type": "csv",
            "status": "completed",
            "currency_mismatch": False,
            "created_by": cls.created_by,
        }).execute()

        # Insert deterministic transactions
        cls.txns = [
            _txn("2024-01-01", 100000, "Revenue Alpha", "ACC-1", cls.doc_id, cls.deal_id),
            _txn("2024-01-15", -30000, "Supplier Beta", "ACC-1", cls.doc_id, cls.deal_id),
            _txn("2024-02-01", 70000, "Revenue Gamma", "ACC-2", cls.doc_id, cls.deal_id),
        ]
        rows_for_db = []
        for t in cls.txns:
            row = {k: v for k, v in t.items() if k != "abs_amount_cents"}
            rows_for_db.append(row)
        cls.sb.table("pds_raw_transactions").insert(rows_for_db).execute()

    @classmethod
    def tearDownClass(cls):
        try:
            for sid in cls.snapshot_ids:
                pass  # immutability trigger blocks deletes; leave for cascade
            for rid in cls.analysis_run_ids:
                pass  # leave for cascade
            cls.sb.table("pds_raw_transactions").delete().eq("deal_id", cls.deal_id).execute()
        except Exception:
            pass
        try:
            cls.sb.table("pds_documents").delete().eq("deal_id", cls.deal_id).execute()
        except Exception:
            pass
        # snapshots/runs blocked by trigger; delete deal to cascade what we can
        try:
            # analysis_runs have ON DELETE RESTRICT on snapshots, so delete snapshots first
            # but trigger blocks that — so we accept some orphans in test DB
            cls.sb.table("pds_analysis_runs").delete().eq("deal_id", cls.deal_id).execute()
        except Exception:
            pass
        try:
            cls.sb.table("pds_deals").delete().eq("id", cls.deal_id).execute()
        except Exception:
            pass

    def _run_export(self, overrides=None):
        """Run the pipeline + export against the live Supabase snapshot repo."""
        overrides = overrides or []
        raw = self.__class__.txns
        run, links, entities, txn_map = run_pipeline(
            deal_id=self.deal_id,
            raw_transactions=[dict(t) for t in raw],
            overrides=overrides,
            accrual={},
        )
        payload = build_pds_payload(
            schema_version=run["schema_version"],
            config_version=run["config_version"],
            deal_id=self.deal_id,
            currency="USD",
            raw_transactions=raw,
            transfer_links=links,
            entities=entities,
            txn_entity_map=txn_map,
            metrics={
                "coverage_bp": run["coverage_pct_bp"],
                "missing_month_count": run["missing_month_count"],
                "missing_month_penalty_bp": run["missing_month_penalty_bp"],
                "reconciliation_status": run["reconciliation_status"],
                "reconciliation_bp": run["reconciliation_pct_bp"],
            },
            confidence={
                "final_confidence_bp": run["final_confidence_bp"],
                "tier": run["tier"],
                "tier_capped": run["tier_capped"],
                "override_penalty_bp": run["override_penalty_bp"],
            },
            overrides_applied=overrides,
        )

        # Persist analysis run in Supabase. bank_operational_inflow_cents is a
        # payload-only field (set in the run dict for the API response) and is
        # deliberately NOT a pds_analysis_runs column — production strips it
        # before every insert (api.py:890, musa_file_processor.py:135). Mirror
        # that strip here; inserting the raw run dict would otherwise be rejected
        # by PostgREST for the unknown column.
        run_for_db = {k: v for k, v in run.items() if k != "bank_operational_inflow_cents"}
        self.sb.table("pds_analysis_runs").insert(run_for_db).execute()
        self.__class__.analysis_run_ids.append(run["id"])

        snapshot = export_snapshot(
            snapshot_repo=_SBSnapshotRepo(self.sb),
            deal_id=self.deal_id,
            analysis_run_id=run["id"],
            payload=payload,
            created_by=self.created_by,
        )
        self.__class__.snapshot_ids.append(snapshot["id"])
        return run, snapshot

    def test_01_document_status_completed(self):
        res = self.sb.table("pds_documents").select("status").eq("id", self.doc_id).execute()
        self.assertEqual(res.data[0]["status"], "completed")

    def test_02_export_idempotent(self):
        run_a, snap_a = self._run_export()
        self.assertIn("sha256_hash", snap_a)
        self.assertIn("financial_state_hash", snap_a)

        run_b, snap_b = self._run_export()
        self.assertEqual(snap_a["id"], snap_b["id"], "Same state → same snapshot id")
        self.assertEqual(snap_a["sha256_hash"], snap_b["sha256_hash"])

    def test_03_override_changes_hashes(self):
        _, snap_pre = self._run_export()

        entity_norm = normalize_descriptor("Revenue Alpha")
        entity_id = hashlib.sha256(
            f"{self.deal_id}|{entity_norm}".encode()
        ).hexdigest()
        ov = {
            "entity_id": entity_id,
            "weight": 1.0,
            "created_at": "2024-06-01T00:00:00Z",
        }
        _, snap_post = self._run_export(overrides=[ov])

        self.assertNotEqual(snap_pre["sha256_hash"], snap_post["sha256_hash"])
        self.assertNotEqual(
            snap_pre.get("financial_state_hash"),
            snap_post.get("financial_state_hash"),
        )

    def test_04_revert_dual_hash_semantics(self):
        _, snap_baseline = self._run_export()

        entity_norm = normalize_descriptor("Revenue Alpha")
        entity_id = hashlib.sha256(
            f"{self.deal_id}|{entity_norm}".encode()
        ).hexdigest()

        ov_apply = {
            "entity_id": entity_id,
            "weight": 1.0,
            "created_at": "2024-06-01T00:00:00Z",
        }
        _, snap_after_ov = self._run_export(overrides=[ov_apply])
        self.assertNotEqual(snap_baseline["sha256_hash"], snap_after_ov["sha256_hash"])

        ov_revert = {
            "entity_id": entity_id,
            "weight": 0.0,
            "created_at": "2024-06-02T00:00:00Z",
        }
        _, snap_reverted = self._run_export(overrides=[ov_apply, ov_revert])

        self.assertEqual(
            snap_baseline.get("financial_state_hash"),
            snap_reverted.get("financial_state_hash"),
            "financial_state_hash must revert to baseline after override neutralised",
        )
        self.assertNotEqual(
            snap_baseline["sha256_hash"],
            snap_reverted["sha256_hash"],
            "sha256_hash must differ (provenance includes override audit trail)",
        )

    def test_05_immutability_trigger(self):
        """Verify that UPDATE and DELETE on pds_snapshots are blocked."""
        snaps = self.sb.table("pds_snapshots").select("id").eq(
            "deal_id", self.deal_id
        ).limit(1).execute()
        if not snaps.data:
            self.skipTest("No snapshots to test immutability against")
        sid = snaps.data[0]["id"]

        with self.assertRaises(Exception, msg="UPDATE must be blocked by trigger"):
            self.sb.table("pds_snapshots").update(
                {"canonical_json": '{"mutated":true}'}
            ).eq("id", sid).execute()

        with self.assertRaises(Exception, msg="DELETE must be blocked by trigger"):
            self.sb.table("pds_snapshots").delete().eq("id", sid).execute()


if __name__ == "__main__":
    unittest.main(verbosity=2)
