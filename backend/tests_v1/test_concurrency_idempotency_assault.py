"""
Concurrency + idempotency assault harness for Parity v1.
Uses in-memory repositories (no Supabase) and httpx.AsyncClient to simulate
parallel requests and races.
"""

import asyncio
import io
import os
import sys
import unittest
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import httpx
from fastapi import FastAPI

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.v1.api import router as v1_router
from backend.v1.db.memory_repositories import build_memory_repos
from backend.v1.core.pipeline import run_pipeline
from backend.v1.core.snapshot_engine import build_pds_payload, canonicalize_payload
from backend.v1.parsing.common import normalize_descriptor


VALID_CSV = """date,amount,description,account_id
2024-01-01,1000,Revenue,ACC-1
2024-01-02,-400,Supplier,ACC-1
"""


def _make_app():
    repos = build_memory_repos()
    app = FastAPI()
    app.state.repos_factory = lambda: repos
    app.include_router(v1_router)
    return app, repos


async def _async_client(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _expected_hashes(repos, deal_id: str, overrides: List[Dict[str, Any]]) -> Tuple[str, str]:
    raw = list(repos["raw"].list_by_deal(deal_id))
    run, links, entities, txn_map = run_pipeline(
        deal_id=deal_id, raw_transactions=raw, overrides=overrides, accrual={}
    )
    # mirror API behavior: replace txn_id with UUID when available
    txn_id_to_uuid = {tx["txn_id"]: tx["id"] for tx in raw if "id" in tx}
    for rec in txn_map:
        tid = rec["txn_id"]
        if tid in txn_id_to_uuid:
            rec["txn_id"] = txn_id_to_uuid[tid]
    payload = build_pds_payload(
        schema_version=run["schema_version"],
        config_version=run["config_version"],
        deal_id=deal_id,
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
    _, sha = canonicalize_payload(payload)
    return sha, payload["financial_state_hash"]


def _entity_id_for_first_raw(repos, deal_id: str) -> str:
    raw = list(repos["raw"].list_by_deal(deal_id))
    if not raw:
        raise AssertionError("No raw transactions present")
    first = raw[0]
    normalized = normalize_descriptor(first.get("normalized_descriptor") or first.get("parsed_descriptor"))
    import hashlib

    return hashlib.sha256(f"{deal_id}|{normalized}".encode("utf-8")).hexdigest()


class TestConcurrencyAssault(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app, self.repos = _make_app()
        self.client = await _async_client(self.app)

        # PAR-196: export() unconditionally instantiates a live-Supabase
        # AuditedFinancialsRepo and calls generate_reconciliation_section()
        # (itself live-Supabase-dependent via calculate_account_coverage ->
        # _get_audited_financials) -- bypassing this file's own in-memory
        # repos_factory entirely. Neither was mocked here, contradicting
        # this module's own docstring ("no external dependencies (no
        # Supabase...)"). Same pre-existing gap test_par77_override_survives_
        # reexport.py already works around for AuditedFinancialsRepo.
        #
        # This isn't cosmetic: generate_reconciliation_section() NEVER
        # returns None (its internal _safe_call always returns a dict, even
        # on failure), so build_pds_payload() always seals a real
        # "recon_section" key into every export() payload. test_override_
        # export_race_consistency's _expected_hashes() helper never passes
        # recon_section, so its independently-reconstructed payload can
        # NEVER match export()'s real sha256_hash -- a permanent,
        # deterministic mismatch since recon_section sealing landed
        # (8ff184c, 2026-06-25), unrelated to concurrency timing. Confirmed
        # via a zero-concurrency control run: the exact same mismatch
        # reproduces with no race involved at all. Disabling recon_section
        # here (matching this test's own explicit "no Supabase" scope --
        # reconciliation reporting is irrelevant to what this file tests)
        # makes both sides agree again.
        self._af_patcher = patch("backend.v1.db.supabase_repositories.AuditedFinancialsRepo")
        mock_af_cls = self._af_patcher.start()
        mock_af_cls.return_value.get_by_deal_id.return_value = []
        # PAR-238: export() now also calls get_latest_confirmed() to source
        # reconciliation's accrual figures — an unconfigured MagicMock here
        # would flow into compute_metrics() as accrual_revenue_cents and
        # blow up on `> 0`. None matches "no audited financials", same as
        # get_by_deal_id returning [] above.
        mock_af_cls.return_value.get_latest_confirmed.return_value = None

        self._recon_patcher = patch(
            "backend.v1.analysis.snapshot_generator.generate_reconciliation_section",
            side_effect=RuntimeError("recon_section disabled in concurrency/idempotency tests (PAR-196)"),
        )
        self._recon_patcher.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        self._recon_patcher.stop()
        self._af_patcher.stop()

    async def _prep_deal_with_doc(self) -> str:
        resp = await self.client.post("/v1/deals", data={"currency": "USD"})
        deal_id = resp.json()["deal"]["id"]
        f = io.BytesIO(VALID_CSV.encode())
        up = await self.client.post(
            f"/v1/deals/{deal_id}/documents",
            files={"file": ("t.csv", f, "text/csv")},
        )
        assert up.status_code == 200
        return deal_id

    async def test_export_idempotency_under_concurrency(self):
        deal_id = await self._prep_deal_with_doc()

        async def do_export():
            return await self.client.post(f"/v1/deals/{deal_id}/export")

        responses = await asyncio.gather(*[do_export() for _ in range(10)])
        self.assertTrue(all(r.status_code == 200 for r in responses))
        snap_ids = {r.json()["snapshot"]["id"] for r in responses}
        sha_vals = {r.json()["snapshot"]["sha256_hash"] for r in responses}
        self.assertEqual(len(snap_ids), 1, "Exports must be idempotent on sha256_hash")
        self.assertEqual(len(sha_vals), 1)
        snaps = self.repos["snapshots"].list_snapshots(deal_id)
        self.assertEqual(len(snaps), 1, "Only one snapshot stored for identical state")

    async def test_override_export_race_consistency(self):
        deal_id = await self._prep_deal_with_doc()
        entity_id = _entity_id_for_first_raw(self.repos, deal_id)

        sha_pre, fin_pre = _expected_hashes(self.repos, deal_id, [])

        async def apply_override():
            return await self.client.post(
                f"/v1/deals/{deal_id}/overrides",
                data={"entity_id": entity_id, "weight": 1.0, "new_value": "payroll"},
            )

        async def do_export():
            return await self.client.post(f"/v1/deals/{deal_id}/export")

        override_task = asyncio.create_task(apply_override())
        export_task = asyncio.create_task(do_export())
        resp_override, resp_export = await asyncio.gather(override_task, export_task)
        self.assertEqual(resp_override.status_code, 200)
        self.assertEqual(resp_export.status_code, 200)

        # Recompute post-override expectation using the actual override (with created_at)
        overrides = list(self.repos["overrides"].list_overrides(deal_id))
        sha_post, fin_post = _expected_hashes(self.repos, deal_id, overrides)

        snap = resp_export.json()["snapshot"]
        sha_seen = snap["sha256_hash"]
        fin_seen = snap["financial_state_hash"]
        self.assertIn((sha_seen, fin_seen), {(sha_pre, fin_pre), (sha_post, fin_post)})

        # Subsequent export after override should be post-override hash
        resp_after = await self.client.post(f"/v1/deals/{deal_id}/export")
        snap_after = resp_after.json()["snapshot"]
        self.assertEqual(snap_after["sha256_hash"], sha_post)
        self.assertEqual(snap_after["financial_state_hash"], fin_post)

    async def test_apply_revert_correctness(self):
        deal_id = await self._prep_deal_with_doc()
        entity_id = _entity_id_for_first_raw(self.repos, deal_id)

        exp_a = await self.client.post(f"/v1/deals/{deal_id}/export")
        snap_a = exp_a.json()["snapshot"]

        await self.client.post(
            f"/v1/deals/{deal_id}/overrides",
            data={"entity_id": entity_id, "weight": 1.0, "new_value": "payroll"},
        )
        exp_b = await self.client.post(f"/v1/deals/{deal_id}/export")
        snap_b = exp_b.json()["snapshot"]

        await self.client.post(
            f"/v1/deals/{deal_id}/overrides",
            data={"entity_id": entity_id, "weight": 0.0, "new_value": "payroll"},
        )
        exp_c = await self.client.post(f"/v1/deals/{deal_id}/export")
        snap_c = exp_c.json()["snapshot"]

        self.assertNotEqual(snap_a["sha256_hash"], snap_b["sha256_hash"])
        self.assertEqual(snap_c["financial_state_hash"], snap_a["financial_state_hash"])
        self.assertNotEqual(snap_c["sha256_hash"], snap_a["sha256_hash"])

        exp_d = await self.client.post(f"/v1/deals/{deal_id}/export")
        self.assertEqual(exp_d.json()["snapshot"]["sha256_hash"], snap_c["sha256_hash"])

    async def test_concurrent_ingest_completion(self):
        resp = await self.client.post("/v1/deals", data={"currency": "USD"})
        deal_id = resp.json()["deal"]["id"]

        async def upload(name: str):
            f = io.BytesIO(VALID_CSV.encode())
            return await self.client.post(
                f"/v1/deals/{deal_id}/documents",
                files={"file": (name, f, "text/csv")},
            )

        r1, r2 = await asyncio.gather(upload("a.csv"), upload("b.csv"))
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

        docs = self.repos["documents"].list_by_deal(deal_id)
        self.assertEqual(len(docs), 2)
        self.assertTrue(all(d["status"] == "completed" for d in docs))

    async def test_export_blocked_when_docs_processing(self):
        resp = await self.client.post("/v1/deals", data={"currency": "USD"})
        deal_id = resp.json()["deal"]["id"]
        # Insert a processing doc directly
        self.repos["documents"].create_document(
            {
                "id": "doc-processing",
                "deal_id": deal_id,
                "storage_url": "inline://x",
                "file_type": "csv",
                "status": "processing",
                "currency_mismatch": False,
                "created_by": resp.json()["deal"]["created_by"],
            }
        )
        exp = await self.client.post(f"/v1/deals/{deal_id}/export")
        self.assertEqual(exp.status_code, 409)
        self.assertEqual(exp.json()["detail"]["error_code"], "DOCUMENTS_NOT_READY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
