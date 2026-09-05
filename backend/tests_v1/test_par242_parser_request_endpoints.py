"""
PAR-242 — deal-scoped parser_requests endpoints.

PAR-62's Musa ingestion path already writes a `parser_requests` row on
unrecognized-format detection (backend/v1/integrations/musa_file_processor.py),
but until now nothing surfaced that row to the deal's own user until the 24h
SLA sweep force-closed it silently. These two endpoints let the web app show
the same "Request parser" prompt already used for direct-upload failures
(UnknownParserModal) and let a human enrich the auto-created row in place --
never a second insert for the same detected failure.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.v1.api import router as v1_router
from backend.v1.db.memory_repositories import build_memory_repos


def _make_app():
    repos = build_memory_repos()
    app = FastAPI()
    app.state.repos_factory = lambda: repos
    app.include_router(v1_router)
    return app, repos


class TestListParserRequestsForDeal(unittest.TestCase):
    def setUp(self):
        self.app, self.repos = _make_app()
        self.client = TestClient(self.app)
        self.deal = self.repos["deals"].create_deal({"id": "deal-1", "company_name": "Buildex"})

    def test_404_for_unknown_deal(self):
        resp = self.client.get("/v1/deals/does-not-exist/parser-requests")
        self.assertEqual(resp.status_code, 404)

    def test_empty_when_no_pending_requests(self):
        resp = self.client.get(f"/v1/deals/{self.deal['id']}/parser-requests")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["parser_requests"], [])

    def test_returns_pending_musa_row(self):
        self.repos["parser_requests"].seed({
            "id": "pr-1", "partner": "musa", "deal_id": self.deal["id"],
            "market": "Kenya", "bank_name": None,
            "error_message": "Bank format not recognised",
            "document_url": "https://signed.example/statement.pdf",
            "status": "pending", "requested_at": "2026-09-01T00:00:00Z",
        })
        resp = self.client.get(f"/v1/deals/{self.deal['id']}/parser-requests")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["parser_requests"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "pr-1")
        self.assertEqual(rows[0]["error_message"], "Bank format not recognised")

    def test_excludes_non_pending_and_other_deals(self):
        self.repos["parser_requests"].seed({
            "id": "pr-done", "partner": "musa", "deal_id": self.deal["id"],
            "status": "done", "requested_at": "2026-09-01T00:00:00Z",
        })
        self.repos["parser_requests"].seed({
            "id": "pr-other-deal", "partner": "musa", "deal_id": "some-other-deal",
            "status": "pending", "requested_at": "2026-09-01T00:00:00Z",
        })
        self.repos["parser_requests"].seed({
            "id": "pr-manual", "partner": "gbfund", "deal_id": self.deal["id"],
            "status": "pending", "requested_at": "2026-09-01T00:00:00Z",
        })
        resp = self.client.get(f"/v1/deals/{self.deal['id']}/parser-requests")
        self.assertEqual(resp.json()["parser_requests"], [])


class TestEnrichParserRequest(unittest.TestCase):
    def setUp(self):
        self.app, self.repos = _make_app()
        self.client = TestClient(self.app)
        self.deal = self.repos["deals"].create_deal({"id": "deal-1", "company_name": "Buildex"})
        self.repos["parser_requests"].seed({
            "id": "pr-1", "partner": "musa", "deal_id": self.deal["id"],
            "market": "Kenya", "bank_name": None,
            "error_message": "Bank format not recognised",
            "status": "pending", "requested_at": "2026-09-01T00:00:00Z",
        })

    def test_404_for_unknown_deal(self):
        resp = self.client.patch(
            "/v1/deals/does-not-exist/parser-requests/pr-1", json={"bank_name": "KCB"}
        )
        self.assertEqual(resp.status_code, 404)

    def test_404_for_request_not_belonging_to_deal(self):
        resp = self.client.patch(
            f"/v1/deals/{self.deal['id']}/parser-requests/does-not-exist", json={"bank_name": "KCB"}
        )
        self.assertEqual(resp.status_code, 404)

    def test_updates_bank_name_and_moves_status_to_in_progress(self):
        resp = self.client.patch(
            f"/v1/deals/{self.deal['id']}/parser-requests/pr-1", json={"bank_name": "KCB"}
        )
        self.assertEqual(resp.status_code, 200)
        updated = resp.json()["parser_request"]
        self.assertEqual(updated["bank_name"], "KCB")
        self.assertEqual(updated["status"], "in_progress")
        # Confirm it's an in-place update, not a second row.
        self.assertEqual(len(self.repos["parser_requests"]._store), 1)

    def test_notes_append_rather_than_overwrite_original_error_message(self):
        resp = self.client.patch(
            f"/v1/deals/{self.deal['id']}/parser-requests/pr-1",
            json={"bank_name": "KCB", "notes": "It's a CSV export, not a PDF"},
        )
        updated = resp.json()["parser_request"]
        self.assertIn("Bank format not recognised", updated["error_message"])
        self.assertIn("It's a CSV export, not a PDF", updated["error_message"])

    def test_does_not_regress_status_if_already_in_progress(self):
        self.repos["parser_requests"].enrich("pr-1", self.deal["id"], {"status": "in_progress"})
        resp = self.client.patch(
            f"/v1/deals/{self.deal['id']}/parser-requests/pr-1", json={"bank_name": "KCB"}
        )
        # Engineering may have already picked this up (admin dashboard cycle) --
        # a second human confirming bank_name must not silently reset that.
        self.assertEqual(resp.json()["parser_request"]["status"], "in_progress")


class TestDealNamePreFill(unittest.TestCase):
    """PAR-242 item 2: pre-fill deal_name from whatever's resolvable at the
    exact point of detection, rather than leaving the notification carrying
    only an opaque deal_id."""

    def test_resolved_deal_name_is_passed_to_notify(self):
        from v1.integrations import musa_file_processor as mfp

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

        notify_calls = []

        async def _fake_notify(**kwargs):
            notify_calls.append(kwargs)

        with patch.object(mfp, "get_supabase", return_value=mock_supabase), \
             patch.object(mfp, "_notify_parser_request", AsyncMock(side_effect=_fake_notify)), \
             patch.object(mfp, "_persist_failed_sample", return_value=None), \
             patch.object(mfp, "DealsRepo") as mock_deals_repo_cls:
            mock_deals_repo_cls.return_value.get_deal.return_value = {
                "id": "deal-1", "company_name": "Buildex Interiors",
            }
            asyncio.run(mfp._record_unrecognized_document(
                session_id="s1", deal_id="deal-1", venture_country="Kenya",
                document_url="https://signed.example/x.pdf",
                file_bytes=b"raw", file_name="x.pdf",
                error_message="Bank format not recognised",
            ))

        self.assertEqual(len(notify_calls), 1)
        self.assertEqual(notify_calls[0]["deal_name"], "Buildex Interiors")

    def test_deal_lookup_failure_does_not_block_notify(self):
        """A DealsRepo error at this point must never take down the existing
        parser_requests insert / notification PAR-62 already depends on."""
        from v1.integrations import musa_file_processor as mfp

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

        notify_calls = []

        async def _fake_notify(**kwargs):
            notify_calls.append(kwargs)

        with patch.object(mfp, "get_supabase", return_value=mock_supabase), \
             patch.object(mfp, "_notify_parser_request", AsyncMock(side_effect=_fake_notify)), \
             patch.object(mfp, "_persist_failed_sample", return_value=None), \
             patch.object(mfp, "DealsRepo") as mock_deals_repo_cls:
            mock_deals_repo_cls.return_value.get_deal.side_effect = RuntimeError("db unreachable")
            asyncio.run(mfp._record_unrecognized_document(
                session_id="s1", deal_id="deal-1", venture_country="Kenya",
                document_url="https://signed.example/x.pdf",
                file_bytes=b"raw", file_name="x.pdf",
                error_message="Bank format not recognised",
            ))

        self.assertEqual(len(notify_calls), 1)
        self.assertIsNone(notify_calls[0]["deal_name"])


if __name__ == "__main__":
    unittest.main()
