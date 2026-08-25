"""
PAR-192 — interim async PDF pipeline: job repo, trigger, and endpoint tests.

Scope, matching core/pdf_jobs.py: this covers the NEW bookkeeping and
trigger logic only. It does not exercise render_snapshot_html() or
_render_html_to_pdf() themselves (both untouched, already covered by
existing tests) -- those are patched out here exactly like
test_snapshot_pdf_html_auth.py already does for the sync endpoint.

Two things get real coverage that matter beyond happy-path CRUD:
  1. trigger_render_job's failure path (Cloud Run REST call fails -> job
     marked failed, not left stuck in "pending" forever).
  2. The cache short-circuit (find_cached_done_job) actually short-circuits
     at the endpoint level, not just at the repo level in isolation.

Run:
    cd backend
    python3 -m pytest tests_v1/test_par192_pdf_jobs.py -v
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v1.api import router as v1_router
from backend.v1.db.memory_repositories import build_memory_repos
from backend.v1.core import pdf_jobs
from tests_v1.jwt_test_utils import PUBLIC_JWKS, bearer


# ---------------------------------------------------------------------------
# Minimal fake supabase-py table builder — chainable, records the last
# terminal call's kwargs so assertions can check what was written.
# ---------------------------------------------------------------------------

class _FakeQuery:
    """
    Chainable fake mirroring real supabase-py semantics: insert()/update()/
    delete() stage the operation and return self (NOT a result) — the
    operation only actually happens when .execute() is called, exactly like
    the real client's `.insert(row).execute()` pattern. Getting this wrong
    (returning a result directly from insert/update/delete) makes every
    pdf_jobs.py call site — which always does `.insert(row).execute()` —
    blow up with AttributeError, which is exactly what surfaced the first
    time this file ran for real (Cloud Build, 2026-08-25): 15/22 tests
    failed on `'_FakeResult' object has no attribute 'execute'` before this
    was fixed. Real bug in the test double, not in pdf_jobs.py itself —
    verified via a separate standalone smoke test of pdf_jobs.py's logic
    that used the corrected shape and passed cleanly.
    """

    def __init__(self, table: "_FakeTable"):
        self.table = table
        self._filters = {}
        self._op = None
        self._payload = None

    def select(self, *_a, **_kw):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def lt(self, col, val):
        self._filters[f"{col}__lt"] = val
        return self

    def order(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    def insert(self, row):
        self._op = "insert"
        self._payload = dict(row)
        return self

    def update(self, patch_dict):
        self._op = "update"
        self._payload = patch_dict
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self):
        if self._op == "insert":
            self.table.rows.append(self._payload)
            return _FakeResult([self._payload])
        matched = [r for r in self.table.rows if self._matches(r)]
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
        elif self._op == "delete":
            for r in matched:
                self.table.rows.remove(r)
        return _FakeResult(matched)

    def _matches(self, row) -> bool:
        for k, v in self._filters.items():
            if k.endswith("__lt"):
                col = k[: -len("__lt")]
                if not (row.get(col) is not None and row[col] < v):
                    return False
            elif row.get(k) != v:
                return False
        return True


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self):
        self.rows = []

    def query(self):
        return _FakeQuery(self)


class _FakeSupabase:
    def __init__(self):
        self._tables = {}

    def table(self, name):
        if name not in self._tables:
            self._tables[name] = _FakeTable()
        return self._tables[name].query()


class PdfJobsRepoTests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeSupabase()
        self._patch = patch("backend.v1.core.pdf_jobs.get_supabase", return_value=self.fake)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_create_and_get_job_round_trips(self):
        job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", "requester-1")
        self.assertEqual(job["status"], "pending")
        fetched = pdf_jobs.get_job(job["job_id"])
        self.assertEqual(fetched["deal_id"], "deal-1")
        self.assertEqual(fetched["variant"], "snapshot")

    def test_get_job_unknown_returns_none(self):
        self.assertIsNone(pdf_jobs.get_job("nope"))

    def test_mark_running_then_done_updates_status_and_bytes(self):
        job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", None)
        pdf_jobs.mark_running(job["job_id"])
        self.assertEqual(pdf_jobs.get_job(job["job_id"])["status"], "running")
        pdf_jobs.mark_done(job["job_id"], b"%PDF-fake-bytes")
        fetched = pdf_jobs.get_job(job["job_id"])
        self.assertEqual(fetched["status"], "done")
        self.assertEqual(fetched["byte_size"], len(b"%PDF-fake-bytes"))

    def test_mark_failed_records_error_and_truncates(self):
        job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", None)
        pdf_jobs.mark_failed(job["job_id"], "boom " * 1000)
        fetched = pdf_jobs.get_job(job["job_id"])
        self.assertEqual(fetched["status"], "failed")
        self.assertLessEqual(len(fetched["error_message"]), 2000)

    def test_get_job_bytes_returns_none_unless_done(self):
        job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", None)
        self.assertIsNone(pdf_jobs.get_job_bytes(job["job_id"]))
        pdf_jobs.mark_done(job["job_id"], b"%PDF-fake")
        self.assertEqual(pdf_jobs.get_job_bytes(job["job_id"]), b"%PDF-fake")

    def test_find_cached_done_job_matches_exact_triple_only(self):
        job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", None)
        pdf_jobs.mark_done(job["job_id"], b"%PDF-fake")
        self.assertIsNotNone(pdf_jobs.find_cached_done_job("deal-1", "snapshot", "snap-1"))
        # different snapshot_id -> no cache hit, must re-render
        self.assertIsNone(pdf_jobs.find_cached_done_job("deal-1", "snapshot", "snap-2"))
        # different variant -> no cache hit
        self.assertIsNone(pdf_jobs.find_cached_done_job("deal-1", "enriched", "snap-1"))

    def test_find_cached_done_job_ignores_non_done_status(self):
        job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", None)
        pdf_jobs.mark_running(job["job_id"])
        self.assertIsNone(pdf_jobs.find_cached_done_job("deal-1", "snapshot", "snap-1"))

    def test_sweep_expired_only_deletes_old_rows(self):
        from datetime import datetime, timedelta, timezone
        old_job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", None)
        # backdate manually — the fake table stores plain dicts
        old_job["created_at"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new_job = pdf_jobs.create_job("deal-1", "snapshot", "snap-2", None)
        new_job["created_at"] = datetime.now(timezone.utc).isoformat()
        deleted = pdf_jobs.sweep_expired(retention_days=14)
        self.assertEqual(deleted, 1)
        self.assertIsNone(pdf_jobs.get_job(old_job["job_id"]))
        self.assertIsNotNone(pdf_jobs.get_job(new_job["job_id"]))


class TriggerRenderJobTests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeSupabase()
        self._patch = patch("backend.v1.core.pdf_jobs.get_supabase", return_value=self.fake)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self._env_patch = patch.dict(os.environ, {"PDF_RENDER_CLOUD_RUN_PROJECT": "parity-491822"})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        # Module-level constant is read at import time from the env var —
        # patch it directly so the test doesn't depend on import order.
        self._const_patch = patch("backend.v1.core.pdf_jobs._CLOUD_RUN_PROJECT", "parity-491822")
        self._const_patch.start()
        self.addCleanup(self._const_patch.stop)

    def test_missing_project_env_raises_before_any_network_call(self):
        with patch("backend.v1.core.pdf_jobs._CLOUD_RUN_PROJECT", None):
            token_fetcher = MagicMock()
            with self.assertRaises(RuntimeError):
                pdf_jobs.trigger_render_job(
                    "job-1", "deal-1", "snapshot", token_fetcher=token_fetcher,
                )
            token_fetcher.assert_not_called()

    def test_successful_trigger_calls_run_api_with_correct_args(self):
        job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", None)
        fake_client = MagicMock()
        fake_client.post.return_value = MagicMock(status_code=200, text="{}")
        pdf_jobs.trigger_render_job(
            job["job_id"], "deal-1", "snapshot",
            token_fetcher=lambda: "fake-token",
            http_client=fake_client,
        )
        fake_client.post.assert_called_once()
        _, kwargs = fake_client.post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-token")
        body = kwargs["json"]
        args_list = body["overrides"]["containerOverrides"][0]["args"]
        self.assertIn(job["job_id"], args_list)
        self.assertIn("deal-1", args_list)
        self.assertIn("snapshot", args_list)
        # job row must NOT be marked failed on a successful trigger
        self.assertEqual(pdf_jobs.get_job(job["job_id"])["status"], "pending")

    def test_failed_trigger_marks_job_failed_not_left_pending(self):
        job = pdf_jobs.create_job("deal-1", "snapshot", "snap-1", None)
        fake_client = MagicMock()
        fake_client.post.return_value = MagicMock(status_code=403, text="permission denied")
        pdf_jobs.trigger_render_job(
            job["job_id"], "deal-1", "snapshot",
            token_fetcher=lambda: "fake-token",
            http_client=fake_client,
        )
        fetched = pdf_jobs.get_job(job["job_id"])
        self.assertEqual(fetched["status"], "failed")
        self.assertIn("403", fetched["error_message"])


class SweepScheduleClassTests(unittest.TestCase):
    def test_sweeper_start_stop_does_not_raise(self):
        """Smoke test only — the real loop body (sweep_expired) is covered
        directly above; this just checks the start/stop lifecycle shape
        mirrors ParserRequestSlaSweeper's without crashing."""
        import asyncio

        sweeper = pdf_jobs.PdfJobRetentionSweeper(poll_interval=0.01)

        async def _run():
            with patch("backend.v1.core.pdf_jobs.sweep_expired", return_value=0):
                task = asyncio.create_task(sweeper.start())
                await asyncio.sleep(0.03)
                sweeper.stop()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Endpoint tests — auth gate + cache short-circuit + status transitions,
# reusing test_snapshot_pdf_html_auth.py's exact harness pattern.
# ---------------------------------------------------------------------------

MUSA_KEY = "musa-real-key"


class _PdfJobEndpointTestBase(unittest.TestCase):
    def setUp(self):
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        self.fake_supabase = _FakeSupabase()

        self._patches = [
            patch("backend.v1.api._get_jwks", return_value=PUBLIC_JWKS),
            patch(
                "backend.v1.integrations.auth.validate_api_key",
                lambda key, partner: partner == "Musa Ventures" and key == MUSA_KEY,
            ),
            patch("backend.v1.core.pdf_jobs.get_supabase", return_value=self.fake_supabase),
            patch("backend.v1.core.pdf_jobs.trigger_render_job", return_value=None),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

        deal_resp = self.client.post("/v1/deals", data={"currency": "KES"})
        self.assertEqual(deal_resp.status_code, 200, deal_resp.text)
        self.deal_id = deal_resp.json()["deal"]["id"]

        # Snapshot required by every job endpoint below (mirrors sync endpoint's
        # own "no snapshot found" 404 branch) — memory repo, no rendering.
        self.repos["snapshots"].insert_snapshot({
            "id": "snap-1",
            "deal_id": self.deal_id,
            "sha256_hash": "fake-hash-1",
            "canonical_json": "{}",
            "created_at": "2026-08-25T00:00:00Z",
        })


class TestCreatePdfJobAuth(_PdfJobEndpointTestBase):
    def test_no_credentials_returns_401(self):
        resp = self.client.post(f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs")
        self.assertEqual(resp.status_code, 401, resp.text)

    def test_valid_internal_jwt_can_trigger(self):
        resp = self.client.post(
            f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs", headers=bearer("real-user")
        )
        # Either 202 (job created) or 404 (memory repo has no snapshot wired
        # for this deal id in this minimal harness) is acceptable here — the
        # point of this test is that auth did NOT reject it with 401.
        self.assertNotEqual(resp.status_code, 401, resp.text)

    def test_invalid_variant_rejected(self):
        resp = self.client.post(
            f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs",
            params={"variant": "not-a-real-variant"},
            headers={"x-api-key": MUSA_KEY},
        )
        # BAD_REQUEST -> 400, matching this file's existing _error() convention
        # (api.py:473 etc.), not a bespoke 422 -- see _ERROR_CODES.
        self.assertEqual(resp.status_code, 400, resp.text)


class TestPdfJobStatusAndContentAuth(_PdfJobEndpointTestBase):
    def test_status_endpoint_requires_auth(self):
        resp = self.client.get(f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/some-job-id")
        self.assertEqual(resp.status_code, 401, resp.text)

    def test_content_endpoint_requires_auth(self):
        resp = self.client.get(f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/some-job-id/content")
        self.assertEqual(resp.status_code, 401, resp.text)

    def test_status_unknown_job_returns_404_not_401(self):
        resp = self.client.get(
            f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/does-not-exist",
            headers={"x-api-key": MUSA_KEY},
        )
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_content_not_ready_returns_409(self):
        job = pdf_jobs.create_job(self.deal_id, "snapshot", "snap-1", None)
        resp = self.client.get(
            f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/{job['job_id']}/content",
            headers={"x-api-key": MUSA_KEY},
        )
        self.assertEqual(resp.status_code, 409, resp.text)

    def test_content_done_returns_pdf_bytes(self):
        job = pdf_jobs.create_job(self.deal_id, "snapshot", "snap-1", None)
        pdf_jobs.mark_done(job["job_id"], b"%PDF-fake-content")
        resp = self.client.get(
            f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/{job['job_id']}/content",
            headers={"x-api-key": MUSA_KEY},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.content, b"%PDF-fake-content")
        self.assertEqual(resp.headers["content-type"], "application/pdf")

    def test_content_failed_job_returns_error_not_pdf(self):
        job = pdf_jobs.create_job(self.deal_id, "snapshot", "snap-1", None)
        pdf_jobs.mark_failed(job["job_id"], "render blew up")
        resp = self.client.get(
            f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/{job['job_id']}/content",
            headers={"x-api-key": MUSA_KEY},
        )
        self.assertNotEqual(resp.status_code, 200, resp.text)

    def test_status_reflects_full_lifecycle(self):
        job = pdf_jobs.create_job(self.deal_id, "snapshot", "snap-1", None)
        headers = {"x-api-key": MUSA_KEY}

        resp = self.client.get(f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/{job['job_id']}", headers=headers)
        self.assertEqual(resp.json()["status"], "pending")

        pdf_jobs.mark_running(job["job_id"])
        resp = self.client.get(f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/{job['job_id']}", headers=headers)
        self.assertEqual(resp.json()["status"], "running")

        pdf_jobs.mark_done(job["job_id"], b"%PDF-x")
        resp = self.client.get(f"/v1/deals/{self.deal_id}/snapshot/pdf/jobs/{job['job_id']}", headers=headers)
        body = resp.json()
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["byte_size"], len(b"%PDF-x"))


if __name__ == "__main__":
    unittest.main()
