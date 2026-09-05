"""
Tests for the Musa Ventures integration.

Covers:
  - SessionResponse shape consistency (POST ≡ GET status ≡ webhook payload)
  - API key authentication enforcement
  - Country → currency mapping
  - File extension inference
  - Webhook payload structure
  - Error state handling

Run:
    cd backend
    python3 -m pytest v1/tests/test_musa_integration.py -v
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    """FastAPI test app with in-memory repos injected via app.state."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from v1.integrations.musa_api import router as musa_router

    _app = FastAPI()
    _app.include_router(musa_router)
    return _app


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


VALID_API_KEY = "mklivemH-zWgAzc8Sg9gcpZIm9r-nfZnsSgpr4skCcQuub3r8"
VALID_HEADERS = {"x-api-key": VALID_API_KEY}

VALID_SESSION_BODY = {
    "venture_name":    "Test Venture Ltd",
    "venture_country": "Kenya",
    "document_urls": [
        {
            "url":       "https://example.com/signed/bank_statement.pdf",
            "file_type": "bank_statement",
            "date_from": "2025-01-01",
            "date_to":   "2025-12-31",
        }
    ],
}

# Expected fields in every SessionResponse
_SESSION_RESPONSE_FIELDS = {
    "session_id", "venture_name", "venture_country",
    "status", "status_url",
    "pdf_url", "error_message", "created_at", "completed_at",
}


# ---------------------------------------------------------------------------
# Helper: build a fake musa_sessions row
# ---------------------------------------------------------------------------

def _fake_session_row(
    session_id: str,
    status: str = "processing",
    deal_id: Optional[str] = None,
    venture_country: str = "Kenya",
    error_message: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "session_id":      session_id,
        "venture_name":    "Test Venture Ltd",
        "venture_country": venture_country,
        "deal_id":         deal_id or str(uuid.uuid4()),
        "status":          status,
        "created_at":      datetime.now(timezone.utc).isoformat(),
        "completed_at":    completed_at,
        "error_message":   error_message,
    }


# ===========================================================================
# 1. Country → currency mapping
# ===========================================================================

class TestCurrencyMapping:
    def test_known_countries(self):
        from v1.integrations.currency_utils import country_to_currency
        assert country_to_currency("Kenya")        == "KES"
        assert country_to_currency("kenya")        == "KES"
        assert country_to_currency("Uganda")       == "UGX"
        assert country_to_currency("Tanzania")     == "TZS"
        assert country_to_currency("Nigeria")      == "NGN"
        assert country_to_currency("Rwanda")       == "RWF"

    def test_unknown_country_raises(self):
        import pytest
        from v1.integrations.currency_utils import country_to_currency
        with pytest.raises(ValueError, match="Cannot resolve country"):
            country_to_currency("Wakanda")
        with pytest.raises(ValueError, match="Cannot resolve country"):
            country_to_currency("")


# ===========================================================================
# 2. File extension inference
# ===========================================================================

class TestExtensionInference:
    def test_pdf_url(self):
        from v1.integrations.musa_file_processor import _infer_extension
        assert _infer_extension("https://s3.amazonaws.com/bucket/file.pdf?X-Amz-Sig=abc", None) == ".pdf"

    def test_csv_url(self):
        from v1.integrations.musa_file_processor import _infer_extension
        assert _infer_extension("https://example.com/mpesa.csv", None) == ".csv"

    def test_xlsx_url(self):
        from v1.integrations.musa_file_processor import _infer_extension
        assert _infer_extension("https://example.com/report.xlsx", None) == ".xlsx"

    def test_unknown_url_falls_back_to_hint(self):
        from v1.integrations.musa_file_processor import _infer_extension
        assert _infer_extension("https://example.com/signed-url-no-ext", "mpesa") == ".csv"
        assert _infer_extension("https://example.com/signed-url-no-ext", "bank_statement") == ".pdf"

    def test_unknown_url_and_no_hint_defaults_to_pdf(self):
        from v1.integrations.musa_file_processor import _infer_extension
        assert _infer_extension("https://example.com/signed-url-no-ext", None) == ".pdf"

    def test_unsupported_extension_falls_back_to_hint(self):
        from v1.integrations.musa_file_processor import _infer_extension
        # .zip is not allowed — should fall back to hint
        assert _infer_extension("https://example.com/archive.zip", "bank_statement") == ".pdf"


# ===========================================================================
# 3. Authentication
# ===========================================================================

class TestAuthentication:
    def _mock_supabase_for_auth(self, monkeypatch, valid: bool):
        """Patch auth.validate_api_key to return valid/invalid."""
        monkeypatch.setattr(
            "v1.integrations.auth.validate_api_key",
            lambda key, partner: valid,
        )

    def test_missing_api_key_returns_422(self, client):
        resp = client.post("/api/musa/sessions", json=VALID_SESSION_BODY)
        assert resp.status_code == 422  # FastAPI: required header missing

    def test_invalid_api_key_returns_401(self, client, monkeypatch):
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: False)
        resp = client.post(
            "/api/musa/sessions",
            json=VALID_SESSION_BODY,
            headers={"x-api-key": "wrong-key"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid API key"

    def test_invalid_key_on_status_endpoint(self, client, monkeypatch):
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: False)
        resp = client.get(
            "/api/musa/sessions/some-id/status",
            headers={"x-api-key": "wrong-key"},
        )
        assert resp.status_code == 401


# ===========================================================================
# 4. POST /sessions — response shape
# ===========================================================================

class TestCreateSession:
    def _mock_db(self, monkeypatch, session_id: str, deal_id: str):
        """Patch DB calls so create_session succeeds without a real Supabase."""
        # Patch DealsRepo.create_deal
        monkeypatch.setattr(
            "v1.integrations.musa_api.DealsRepo",
            lambda: MagicMock(create_deal=lambda d: {**d, "id": deal_id}),
        )
        # Patch get_supabase → table → insert → execute
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"session_id": session_id, "created_at": datetime.now(timezone.utc).isoformat()}]
        )
        monkeypatch.setattr("v1.integrations.musa_api.get_supabase", lambda: mock_sb)
        # Patch auth
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: True)
        # Suppress background task
        monkeypatch.setattr(
            "v1.integrations.musa_api.process_musa_session",
            lambda **kw: None,
        )

    def test_response_has_all_session_response_fields(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        self._mock_db(monkeypatch, sid, did)

        resp = client.post("/api/musa/sessions", json=VALID_SESSION_BODY, headers=VALID_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert _SESSION_RESPONSE_FIELDS.issubset(data.keys()), (
            f"Missing fields: {_SESSION_RESPONSE_FIELDS - data.keys()}"
        )

    def test_initial_status_is_processing(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        self._mock_db(monkeypatch, sid, did)

        resp = client.post("/api/musa/sessions", json=VALID_SESSION_BODY, headers=VALID_HEADERS)
        assert resp.json()["status"] == "processing"

    def test_pdf_url_is_null_initially(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        self._mock_db(monkeypatch, sid, did)

        resp = client.post("/api/musa/sessions", json=VALID_SESSION_BODY, headers=VALID_HEADERS)
        assert resp.json()["pdf_url"] is None

    def test_status_url_is_well_formed(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        self._mock_db(monkeypatch, sid, did)

        resp = client.post("/api/musa/sessions", json=VALID_SESSION_BODY, headers=VALID_HEADERS)
        status_url = resp.json()["status_url"]
        assert "/api/musa/sessions/" in status_url
        assert "/status" in status_url

    def test_venture_fields_echoed_correctly(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        self._mock_db(monkeypatch, sid, did)

        resp = client.post("/api/musa/sessions", json=VALID_SESSION_BODY, headers=VALID_HEADERS)
        data = resp.json()
        assert data["venture_name"]    == VALID_SESSION_BODY["venture_name"]
        assert data["venture_country"] == VALID_SESSION_BODY["venture_country"]


# ===========================================================================
# 4b. PAR-253 — idempotent-by-choice deal reuse in create_session
# ===========================================================================

class TestCreateSessionDealIdReuse:
    """
    PAR-253: create_session can accept an existing deal_id to reuse instead of
    minting a fresh pds_deals row.
    """

    def _mock_db_with_existing_deal(self, monkeypatch, session_id: str, deal_id: str):
        """Patch DB so DealsRepo.get_deal returns the existing deal and no new deal is created."""
        existing_deal = {"id": deal_id, "name": "Existing Venture", "currency": "KES"}
        deals_repo_mock = MagicMock()
        deals_repo_mock.get_deal.return_value = existing_deal
        # create_deal must NOT be called — if it is, the test will catch it via call_count
        monkeypatch.setattr("v1.integrations.musa_api.DealsRepo", lambda: deals_repo_mock)

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"session_id": session_id, "created_at": datetime.now(timezone.utc).isoformat()}]
        )
        monkeypatch.setattr("v1.integrations.musa_api.get_supabase", lambda: mock_sb)
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: True)
        monkeypatch.setattr("v1.integrations.musa_api.process_musa_session", lambda **kw: None)
        return deals_repo_mock

    def test_provided_deal_id_is_reused_no_new_deal_created(self, client, monkeypatch):
        """When deal_id is given and exists, the session links to it — create_deal is NOT called."""
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        repo_mock = self._mock_db_with_existing_deal(monkeypatch, sid, did)

        body = {**VALID_SESSION_BODY, "deal_id": did}
        resp = client.post("/api/musa/sessions", json=body, headers=VALID_HEADERS)

        assert resp.status_code == 200
        assert repo_mock.create_deal.call_count == 0, "create_deal must not be called when deal_id is reused"
        assert repo_mock.get_deal.call_count == 1
        assert repo_mock.get_deal.call_args[0][0] == did

    def test_missing_deal_id_returns_404(self, client, monkeypatch):
        """When deal_id is provided but doesn't exist, a 404 is returned immediately."""
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())

        deals_repo_mock = MagicMock()
        deals_repo_mock.get_deal.return_value = None  # deal not found
        monkeypatch.setattr("v1.integrations.musa_api.DealsRepo", lambda: deals_repo_mock)
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: True)

        body = {**VALID_SESSION_BODY, "deal_id": did}
        resp = client.post("/api/musa/sessions", json=body, headers=VALID_HEADERS)

        assert resp.status_code == 404
        assert did in resp.json()["detail"]
        assert deals_repo_mock.create_deal.call_count == 0

    def test_no_deal_id_path_is_unchanged(self, client, monkeypatch):
        """When deal_id is omitted, behavior is byte-for-byte identical to the original path."""
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())

        # Use the same mock as the original TestCreateSession tests
        calls = {"create_deal": 0, "get_deal": 0}

        def fake_create_deal(d):
            calls["create_deal"] += 1
            return {**d, "id": did}

        deals_repo_mock = MagicMock()
        deals_repo_mock.create_deal.side_effect = fake_create_deal
        monkeypatch.setattr("v1.integrations.musa_api.DealsRepo", lambda: deals_repo_mock)

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"session_id": sid, "created_at": datetime.now(timezone.utc).isoformat()}]
        )
        monkeypatch.setattr("v1.integrations.musa_api.get_supabase", lambda: mock_sb)
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: True)
        monkeypatch.setattr("v1.integrations.musa_api.process_musa_session", lambda **kw: None)

        # No deal_id field — original body unchanged
        resp = client.post("/api/musa/sessions", json=VALID_SESSION_BODY, headers=VALID_HEADERS)

        assert resp.status_code == 200
        assert calls["create_deal"] == 1, "create_deal must still be called when no deal_id provided"
        assert deals_repo_mock.get_deal.call_count == 0, "get_deal must not be called when no deal_id"
        data = resp.json()
        assert data["status"] == "processing"
        assert data["venture_name"] == VALID_SESSION_BODY["venture_name"]


# ===========================================================================
# 5. GET /sessions/{id}/status — response shape parity
# ===========================================================================

class TestGetStatus:
    def _mock_db(self, monkeypatch, row: Dict[str, Any]):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[row]
        )
        monkeypatch.setattr("v1.integrations.musa_api.get_supabase", lambda: mock_sb)
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: True)

    def test_response_has_all_session_response_fields(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        row = _fake_session_row(sid)
        self._mock_db(monkeypatch, row)

        resp = client.get(f"/api/musa/sessions/{sid}/status", headers=VALID_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert _SESSION_RESPONSE_FIELDS.issubset(data.keys()), (
            f"Missing fields: {_SESSION_RESPONSE_FIELDS - data.keys()}"
        )

    def test_status_matches_db_row(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        row = _fake_session_row(sid, status="complete", completed_at=datetime.now(timezone.utc).isoformat())
        self._mock_db(monkeypatch, row)

        resp = client.get(f"/api/musa/sessions/{sid}/status", headers=VALID_HEADERS)
        assert resp.json()["status"] == "complete"

    def test_pdf_url_populated_when_complete(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        row = _fake_session_row(sid, status="complete", deal_id=did)
        self._mock_db(monkeypatch, row)

        resp = client.get(f"/api/musa/sessions/{sid}/status", headers=VALID_HEADERS)
        pdf_url = resp.json()["pdf_url"]
        assert pdf_url is not None
        assert did in pdf_url
        assert "snapshot/pdf" in pdf_url

    def test_pdf_url_null_when_processing(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        row = _fake_session_row(sid, status="processing")
        self._mock_db(monkeypatch, row)

        resp = client.get(f"/api/musa/sessions/{sid}/status", headers=VALID_HEADERS)
        assert resp.json()["pdf_url"] is None

    def test_error_message_surfaced_when_failed(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        row = _fake_session_row(sid, status="failed", error_message="Download timed out")
        self._mock_db(monkeypatch, row)

        resp = client.get(f"/api/musa/sessions/{sid}/status", headers=VALID_HEADERS)
        assert resp.json()["error_message"] == "Download timed out"

    def test_404_for_unknown_session(self, client, monkeypatch):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )
        monkeypatch.setattr("v1.integrations.musa_api.get_supabase", lambda: mock_sb)
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: True)

        resp = client.get("/api/musa/sessions/nonexistent/status", headers=VALID_HEADERS)
        assert resp.status_code == 404


# ===========================================================================
# 6. Webhook payload shape parity
# ===========================================================================

class TestWebhookPayload:
    def test_webhook_payload_matches_session_response_fields(self, monkeypatch):
        """
        Verify _send_webhook constructs a dict whose keys are identical to
        the fields in SessionResponse.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import _send_webhook

        monkeypatch.setenv("MUSA_WEBHOOK_URL",        "https://webhook.example.com")
        monkeypatch.setenv("MUSA_WEBHOOK_AUTH_TOKEN", "tok_test")

        mock_response = MagicMock(status_code=200)
        mock_post     = AsyncMock(return_value=mock_response)

        mock_client_instance = AsyncMock()
        mock_client_instance.post = mock_post
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__  = AsyncMock(return_value=False)

        with patch("v1.integrations.musa_file_processor.httpx.AsyncClient",
                   return_value=mock_client_instance):
            asyncio.run(_send_webhook(
                session_id="test-sid",
                venture_name="Acme",
                venture_country="Kenya",
                status="complete",
                status_url="https://parity.io/status",
                pdf_url="https://parity.io/pdf",
                created_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-02T00:00:00+00:00",
            ))

        assert mock_post.called, "httpx.AsyncClient.post was not called"
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args.args[1]

        assert _SESSION_RESPONSE_FIELDS.issubset(payload.keys()), (
            f"Webhook missing fields: {_SESSION_RESPONSE_FIELDS - payload.keys()}"
        )

    def test_webhook_skipped_when_env_vars_missing(self, monkeypatch):
        """No HTTP call when MUSA_WEBHOOK_URL is unset."""
        import asyncio
        from v1.integrations.musa_file_processor import _send_webhook

        monkeypatch.delenv("MUSA_WEBHOOK_URL",        raising=False)
        monkeypatch.delenv("MUSA_WEBHOOK_AUTH_TOKEN", raising=False)

        with patch("v1.integrations.musa_file_processor.httpx.AsyncClient") as MockClient:
            asyncio.run(_send_webhook(
                session_id="sid",
                venture_name="X",
                venture_country="Kenya",
                status="complete",
                status_url="https://example.com/status",
            ))
            MockClient.assert_not_called()


# ===========================================================================
# 6b. Setup-phase failures must not escape silently (PAR-60)
# ===========================================================================

class TestNoSilentFailures:
    def test_unresolvable_country_still_fires_failure_webhook(self, monkeypatch):
        """
        Regression test: country_to_currency() (and other setup before the
        old try block) used to raise straight out of process_musa_session,
        which — running as a FastAPI BackgroundTasks job — died silently:
        no status update, no webhook. A session could sit at status=
        "processing" forever with no notification of the underlying 500.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        mock_table = MagicMock()
        mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_table

        sent_webhooks = []

        async def _fake_send_webhook(**kwargs):
            sent_webhooks.append(kwargs)

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-unresolvable-country",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Wakanda",  # unrecognized -> country_to_currency raises
                documents=[{"url": "https://example.com/statement.pdf"}],
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        assert len(sent_webhooks) == 1, "failure webhook was not sent"
        assert sent_webhooks[0]["status"] == "failed"

        # Session status must also be persisted as failed, not left dangling
        # at "processing".
        update_calls = [
            call for call in mock_table.update.call_args_list
            if call.args[0].get("status") == "failed"
        ]
        assert update_calls, "musa_sessions row was never marked failed"

    def test_construction_failure_still_fires_failure_webhook(self, monkeypatch):
        """
        Same guarantee, different trigger: a generic exception during
        repo/service construction (not the currency-resolution path covered
        above) must also be caught by the outer try and still reach the
        failure webhook. Confirms the fix is structural — the whole setup
        phase is inside the try — not a patch for one specific call.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        mock_table = MagicMock()
        mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_table

        sent_webhooks = []

        async def _fake_send_webhook(**kwargs):
            sent_webhooks.append(kwargs)

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            side_effect=RuntimeError("boom: repo construction failed"),
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-construction-failure",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",  # valid — proves the trigger isn't currency
                documents=[{"url": "https://example.com/statement.pdf"}],
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        assert len(sent_webhooks) == 1, "failure webhook was not sent"
        assert sent_webhooks[0]["status"] == "failed"

        update_calls = [
            call for call in mock_table.update.call_args_list
            if call.args[0].get("status") == "failed"
        ]
        assert update_calls, "musa_sessions row was never marked failed"


# ===========================================================================
# 6c. Failed-sample persistence to Storage (PAR-34)
# ===========================================================================

class TestParserRequestStoragePersistence:
    def test_unsupported_format_uploads_sample_and_records_storage_path(self, monkeypatch):
        """
        When a Musa document fails with an unsupported/unparseable format,
        the sample bytes must be uploaded to the `parser-requests` Storage
        bucket and the resulting path recorded on the parser_requests row —
        closing the gap where the signed URL Musa originally gave us expires
        and the file is lost for good.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        inserted_rows = {}
        uploads = {}

        def _fake_table(name):
            tbl = MagicMock()
            if name == "parser_requests":
                def _insert(row):
                    inserted_rows.update(row)
                    return MagicMock(execute=MagicMock(return_value=MagicMock()))
                tbl.insert.side_effect = _insert
            else:
                tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return tbl

        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = _fake_table

        def _fake_upload(path, content, options=None):
            uploads[path] = content
            return MagicMock()

        mock_supabase.storage.from_.return_value.upload.side_effect = _fake_upload

        async def _fake_send_webhook(**kwargs):
            pass

        async def _fake_notify_parser_request(**kwargs):
            pass

        async def _fake_download(url, timeout=300):
            return b"raw-bank-statement-bytes"

        def _raise_unsupported(*args, **kwargs):
            raise ValueError("Unsupported bank format — no recognisable transactions")

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._download_file",
            AsyncMock(side_effect=_fake_download),
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor.IngestionService.process_document_background",
            side_effect=_raise_unsupported,
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ), patch(
            "v1.integrations.musa_file_processor._notify_parser_request",
            AsyncMock(side_effect=_fake_notify_parser_request),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-unsupported-format",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",
                documents=[{"url": "https://example.com/signed/weird_bank.pdf"}],
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        assert len(uploads) == 1, "sample file was not uploaded to storage"
        object_path = next(iter(uploads))
        assert object_path.startswith("musa/test-sid-unsupported-format/")
        assert uploads[object_path] == b"raw-bank-statement-bytes"

        assert inserted_rows.get("storage_path") == object_path

    def test_raw_document_persisted_before_parse_attempt(self, monkeypatch):
        """
        PAR-248: storage upload must happen BEFORE process_document_background
        is called — not after. This ensures storage_path is always populated
        on any parser_requests row, even when the parse raises immediately.
        """
        import asyncio
        from unittest.mock import AsyncMock, call
        from v1.integrations.musa_file_processor import process_musa_session

        call_order = []

        async def _fake_download(url, timeout=300):
            return b"bytes"

        def _fake_upload(path, content, options=None):
            call_order.append("upload")
            return MagicMock()

        def _raise_unsupported(*args, **kwargs):
            call_order.append("parse")
            raise ValueError("Unsupported bank format — no recognisable transactions")

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_supabase.storage.from_.return_value.upload.side_effect = _fake_upload

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._download_file",
            AsyncMock(side_effect=_fake_download),
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor.IngestionService.process_document_background",
            side_effect=_raise_unsupported,
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(),
        ), patch(
            "v1.integrations.musa_file_processor._notify_parser_request",
            AsyncMock(),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-order",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",
                documents=[{"url": "https://example.com/signed/doc.pdf"}],
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        assert call_order == ["upload", "parse"], (
            f"Expected upload before parse, got order: {call_order}"
        )

    def test_unsupported_format_defers_webhook_to_sla_sweep(self, monkeypatch):
        """
        PAR-62: an unrecognized-format failure must NOT fire the failure
        webhook or mark musa_sessions "failed" immediately — that decision
        is deferred to the 24h SLA sweep (musa_parser_request_sla.py).
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        session_updates = []

        def _fake_table(name):
            tbl = MagicMock()
            if name == "parser_requests":
                tbl.insert.return_value.execute.return_value = MagicMock()
            elif name == "musa_sessions":
                def _update(payload):
                    session_updates.append(payload)
                    return MagicMock(eq=MagicMock(
                        return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))
                    ))
                tbl.update.side_effect = _update
            return tbl

        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = _fake_table
        mock_supabase.storage.from_.return_value.upload.return_value = MagicMock()

        webhook_calls = []

        async def _fake_send_webhook(**kwargs):
            webhook_calls.append(kwargs)

        async def _fake_download(url, timeout=300):
            return b"raw-bytes"

        def _raise_unsupported(*args, **kwargs):
            raise ValueError("Unsupported bank format — no recognisable transactions")

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._download_file",
            AsyncMock(side_effect=_fake_download),
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor.IngestionService.process_document_background",
            side_effect=_raise_unsupported,
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ), patch(
            "v1.integrations.musa_file_processor._notify_parser_request",
            AsyncMock(),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-deferred",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",
                documents=[{"url": "https://example.com/signed/weird_bank.pdf"}],
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        assert webhook_calls == [], "failure webhook must not fire immediately for unrecognized format"
        failed_updates = [u for u in session_updates if u.get("status") == "failed"]
        assert not failed_updates, "musa_sessions must not be marked failed immediately"


# ===========================================================================
# 6d. Parser-request SLA sweep (PAR-62)
# ===========================================================================

class TestParserRequestSlaSweep:
    def _row(self, requested_at, **overrides):
        row = {
            "id": str(uuid.uuid4()),
            "partner": "musa",
            "market": "Kenya",
            "document_url": "https://example.com/x.pdf",
            "session_id": "sid-sla-1",
            "deal_id": str(uuid.uuid4()),
            "error_message": "Unsupported bank format",
            "status": "pending",
            "storage_path": "musa/sid-sla-1/x.pdf",
            "requested_at": requested_at,
        }
        row.update(overrides)
        return row

    def test_within_window_retries_and_stays_pending_on_failure(self, monkeypatch):
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations import musa_parser_request_sla as sla

        pending_row = self._row(
            (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        )

        mock_table = MagicMock()
        mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[pending_row])
        )
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_table

        with patch(
            "v1.integrations.musa_parser_request_sla.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.integrations.musa_parser_request_sla._attempt_retry",
            return_value=False,
        ), patch(
            "v1.integrations.musa_parser_request_sla._send_webhook",
            AsyncMock(),
        ) as mock_webhook:
            asyncio.run(sla.sweep_parser_request_sla())

        mock_webhook.assert_not_called()
        update_calls = [
            c for c in mock_table.update.call_args_list
            if c.args[0].get("status") in ("expired", "resolved")
        ]
        assert not update_calls, "row within the SLA window must not be closed"

    def test_expired_force_closes_and_sends_failure_webhook(self, monkeypatch):
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations import musa_parser_request_sla as sla

        expired_row = self._row(
            (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        )
        session_row = {
            "session_id": "sid-sla-1",
            "venture_name": "Acme",
            "venture_country": "Kenya",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        def _fake_table(name):
            tbl = MagicMock()
            if name == "parser_requests":
                tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
                    MagicMock(data=[expired_row])
                )
            elif name == "musa_sessions":
                tbl.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[session_row]
                )
                tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return tbl

        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = _fake_table

        webhook_calls = []

        async def _fake_send_webhook(**kwargs):
            webhook_calls.append(kwargs)

        with patch(
            "v1.integrations.musa_parser_request_sla.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.integrations.musa_parser_request_sla._attempt_retry",
            return_value=False,
        ), patch(
            "v1.integrations.musa_parser_request_sla._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ):
            asyncio.run(sla.sweep_parser_request_sla())

        assert len(webhook_calls) == 1
        assert webhook_calls[0]["status"] == "failed"
        assert webhook_calls[0]["session_id"] == "sid-sla-1"

    def test_successful_retry_resolves_request_and_completes_session(self, monkeypatch):
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations import musa_parser_request_sla as sla

        pending_row = self._row(
            (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        )
        session_row = {
            "session_id": "sid-sla-1",
            "venture_name": "Acme",
            "venture_country": "Kenya",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        def _fake_table(name):
            tbl = MagicMock()
            if name == "parser_requests":
                tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
                    MagicMock(data=[pending_row])
                )
            elif name == "musa_sessions":
                tbl.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[session_row]
                )
                tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return tbl

        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = _fake_table

        webhook_calls = []

        async def _fake_send_webhook(**kwargs):
            webhook_calls.append(kwargs)

        with patch(
            "v1.integrations.musa_parser_request_sla.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.integrations.musa_parser_request_sla._attempt_retry",
            return_value=True,
        ), patch(
            "v1.integrations.musa_parser_request_sla._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ):
            asyncio.run(sla.sweep_parser_request_sla())

        assert len(webhook_calls) == 1
        assert webhook_calls[0]["status"] == "complete"
        assert webhook_calls[0]["session_id"] == "sid-sla-1"

    def test_attempt_retry_success_path_calls_ingestion_and_export(self, monkeypatch):
        """
        _attempt_retry itself: downloads the persisted sample, re-runs
        ingestion against the original deal, and re-exports. Returns True
        when ingestion now succeeds (a parser was shipped in the window).
        """
        from v1.integrations import musa_parser_request_sla as sla

        row = self._row(datetime.now(timezone.utc).isoformat())
        deal = {"id": row["deal_id"], "currency": "KES"}

        mock_supabase = MagicMock()
        mock_supabase.storage.from_.return_value.download.return_value = b"sample-bytes"

        with patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_parser_request_sla.DealsRepo",
        ) as MockDealsRepo, patch(
            "v1.integrations.musa_parser_request_sla.DocumentsRepo",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_parser_request_sla.IngestionService.process_document_background",
            return_value=None,
        ), patch(
            "v1.integrations.musa_parser_request_sla._run_export",
        ) as mock_export:
            MockDealsRepo.return_value.get_deal.return_value = deal
            result = sla._attempt_retry(mock_supabase, row)

        assert result is True
        mock_export.assert_called_once()

    def test_attempt_retry_still_unsupported_returns_false(self, monkeypatch):
        """A retry that still fails must return False, not raise."""
        from v1.integrations import musa_parser_request_sla as sla

        row = self._row(datetime.now(timezone.utc).isoformat())
        deal = {"id": row["deal_id"], "currency": "KES"}

        mock_supabase = MagicMock()
        mock_supabase.storage.from_.return_value.download.return_value = b"sample-bytes"

        with patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_parser_request_sla.DealsRepo",
        ) as MockDealsRepo, patch(
            "v1.integrations.musa_parser_request_sla.DocumentsRepo",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_parser_request_sla.IngestionService.process_document_background",
            side_effect=ValueError("still unsupported"),
        ):
            MockDealsRepo.return_value.get_deal.return_value = deal
            result = sla._attempt_retry(mock_supabase, row)

        assert result is False


# ===========================================================================
# 6e. Partial-batch processing (PAR-61)
# ===========================================================================

class _FakeDocsRepo:
    """
    Minimal real-shaped stand-in for DocumentsRepo (PAR-200). The
    orchestrator now queries the document's row via select_eq("id", ...)
    right after process_document_background returns, to check its actual
    resulting status — a bare MagicMock() silently "succeeds" at every
    attribute/subscript access (MagicMock auto-configures magic methods
    like __getitem__), which previously masked exactly this gap in tests.
    This fake requires the row to genuinely exist and reflect whatever the
    test's mocked process_document_background actually did.
    """

    def __init__(self):
        self.rows: Dict[str, Dict[str, Any]] = {}

    def create_document(self, row):
        self.rows[row["id"]] = dict(row)
        return row

    def select_eq(self, column, value):
        if column != "id":
            return []
        row = self.rows.get(value)
        return [row] if row else []

    def mark_completed(self, document_id):
        self.rows[document_id]["status"] = "completed"

    def mark_failed(self, document_id, *, error_type, error_message, next_action):
        self.rows[document_id].update({
            "status": "failed",
            "error_type": error_type,
            "error_message": error_message,
            "next_action": next_action,
        })


class TestPartialBatchProcessing:
    def _mock_supabase(self):
        session_updates = []
        parser_request_inserts = []

        def _fake_table(name):
            tbl = MagicMock()
            if name == "musa_sessions":
                def _update(payload):
                    session_updates.append(payload)
                    return MagicMock(eq=MagicMock(
                        return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))
                    ))
                tbl.update.side_effect = _update
            elif name == "parser_requests":
                def _insert(row):
                    parser_request_inserts.append(row)
                    return MagicMock(execute=MagicMock(return_value=MagicMock()))
                tbl.insert.side_effect = _insert
            return tbl

        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = _fake_table
        mock_supabase.storage.from_.return_value.upload.return_value = MagicMock()
        return mock_supabase, session_updates, parser_request_inserts

    def test_batch_with_some_unrecognized_still_completes(self, monkeypatch):
        """
        PAR-61: a batch of 3 documents where the middle one is an
        unrecognized format must still process the other two and complete
        the session — not fail the entire batch.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        mock_supabase, session_updates, parser_request_inserts = self._mock_supabase()
        fake_docs_repo = _FakeDocsRepo()

        async def _fake_download(url, timeout=300):
            return b"raw-bytes"

        call_count = {"n": 0}

        def _ingest_side_effect(*, document_id, file_name, **kwargs):
            call_count["n"] += 1
            if "bad" in file_name:
                fake_docs_repo.mark_failed(
                    document_id,
                    error_type="InvalidSchemaError",
                    error_message="Unsupported bank format — no recognisable transactions",
                    next_action="request_parser",
                )
                raise ValueError("Unsupported bank format — no recognisable transactions")
            fake_docs_repo.mark_completed(document_id)
            return None

        webhook_calls = []

        async def _fake_send_webhook(**kwargs):
            webhook_calls.append(kwargs)

        documents = [
            {"url": "https://example.com/signed/good1.pdf"},
            {"url": "https://example.com/signed/bad_format.pdf"},
            {"url": "https://example.com/signed/good2.pdf"},
        ]

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._download_file",
            AsyncMock(side_effect=_fake_download),
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            return_value=fake_docs_repo,
        ), patch(
            "v1.integrations.musa_file_processor.IngestionService.process_document_background",
            side_effect=_ingest_side_effect,
        ), patch(
            "v1.integrations.musa_file_processor._run_export",
            return_value={},
        ) as mock_export, patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ), patch(
            "v1.integrations.musa_file_processor._notify_parser_request",
            AsyncMock(),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-partial-batch",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",
                documents=documents,
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        assert call_count["n"] == 3, "all 3 documents should have been attempted"
        mock_export.assert_called_once()

        complete_updates = [u for u in session_updates if u.get("status") == "complete"]
        assert len(complete_updates) == 1, "session must complete despite one bad document"
        assert "1 could not be processed" in (complete_updates[0].get("error_message") or "")

        assert len(webhook_calls) == 1
        assert webhook_calls[0]["status"] == "complete"
        assert "1 could not be processed" in (webhook_calls[0]["error_message"] or "")

        assert len(parser_request_inserts) == 1
        assert "bad_format.pdf" in parser_request_inserts[0]["document_url"]

    def test_all_unrecognized_defers_every_document(self, monkeypatch):
        """
        PAR-61 + PAR-62 combined: if every document in a batch is an
        unrecognized format, each gets its own parser_requests row (not
        just documents[0]), and the whole session defers to the SLA sweep
        — no immediate failure webhook.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        mock_supabase, session_updates, parser_request_inserts = self._mock_supabase()

        async def _fake_download(url, timeout=300):
            return b"raw-bytes"

        def _raise_unsupported(**kwargs):
            raise ValueError("Unsupported bank format — no recognisable transactions")

        webhook_calls = []

        async def _fake_send_webhook(**kwargs):
            webhook_calls.append(kwargs)

        documents = [
            {"url": "https://example.com/signed/bad1.pdf"},
            {"url": "https://example.com/signed/bad2.pdf"},
        ]

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._download_file",
            AsyncMock(side_effect=_fake_download),
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor.IngestionService.process_document_background",
            side_effect=_raise_unsupported,
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ), patch(
            "v1.integrations.musa_file_processor._notify_parser_request",
            AsyncMock(),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-all-unrecognized",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",
                documents=documents,
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        assert webhook_calls == [], "no immediate webhook when everything is deferred to SLA"
        assert not any(u.get("status") == "failed" for u in session_updates)
        assert len(parser_request_inserts) == 2, "each failing document gets its own parser_requests row"
        urls = {row["document_url"] for row in parser_request_inserts}
        assert urls == {"https://example.com/signed/bad1.pdf", "https://example.com/signed/bad2.pdf"}

    def test_all_fail_with_genuine_error_marks_session_failed(self, monkeypatch):
        """
        If nothing in the batch succeeds and the failures are genuine
        (not format-recognition), the session must still fail immediately
        with a webhook — PAR-61 only relaxes the all-or-nothing rule for
        partial *success*, not total failure.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        mock_supabase, session_updates, parser_request_inserts = self._mock_supabase()

        async def _fake_download_fails(url, timeout=300):
            raise TimeoutError("Request timed out")

        webhook_calls = []

        async def _fake_send_webhook(**kwargs):
            webhook_calls.append(kwargs)

        documents = [{"url": "https://example.com/signed/unreachable.pdf"}]

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._download_file",
            AsyncMock(side_effect=_fake_download_fails),
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-all-genuine-fail",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",
                documents=documents,
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        assert parser_request_inserts == [], "a download timeout is not a parser_requests case"
        assert len(webhook_calls) == 1
        assert webhook_calls[0]["status"] == "failed"
        failed_updates = [u for u in session_updates if u.get("status") == "failed"]
        assert len(failed_updates) == 1


# ===========================================================================
# 6b. PAR-200: orchestrator consumes the REAL per-document outcome
# ===========================================================================

class TestOrchestratorConsumesRealDocumentOutcome:
    """
    PAR-200: process_document_background's real contract is `-> None` and it
    NEVER raises for a genuine per-document parse failure -- it catches
    everything internally (CurrencyMismatchError, InvalidSchemaError,
    IngestionTimeoutError, and a trailing bare Exception) and records the
    outcome on the document's own row via _update_failed(). These tests
    simulate that REAL contract -- unlike TestPartialBatchProcessing above,
    which mocks it as *raising*, a fictional premise that is exactly why the
    real bug went uncaught by that test class. These fail against the
    pre-fix orchestrator, which incremented succeeded_count unconditionally
    right after the awaited call regardless of the document's real
    resulting status.
    """

    def _mock_supabase(self):
        session_updates = []
        parser_request_inserts = []

        def _fake_table(name):
            tbl = MagicMock()
            if name == "musa_sessions":
                def _update(payload):
                    session_updates.append(payload)
                    return MagicMock(eq=MagicMock(
                        return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))
                    ))
                tbl.update.side_effect = _update
            elif name == "parser_requests":
                def _insert(row):
                    parser_request_inserts.append(row)
                    return MagicMock(execute=MagicMock(return_value=MagicMock()))
                tbl.insert.side_effect = _insert
            return tbl

        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = _fake_table
        mock_supabase.storage.from_.return_value.upload.return_value = MagicMock()
        return mock_supabase, session_updates, parser_request_inserts

    def test_succeeded_count_reflects_real_status_not_clean_return(self, monkeypatch):
        """
        4 documents: 1 genuinely completes, 3 fail for 3 DIFFERENT real
        reasons -- none of them ever raise. The pre-fix orchestrator would
        have counted all 4 as succeeded_count and reported "4 of 4
        processed successfully". The fix must report exactly 1 of 4, and
        the two request_parser-classified failures must each produce their
        own parser_requests row (PAR-125's previously-dead auto-request
        path, confirmed reachable now that real failures are visible).
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        mock_supabase, session_updates, parser_request_inserts = self._mock_supabase()
        fake_docs_repo = _FakeDocsRepo()

        async def _fake_download(url, timeout=300):
            return b"raw-bytes"

        # Real per-document outcomes, applied to the fake repo exactly like
        # the real process_document_background would -- write to the row,
        # return None, never raise.
        outcomes = {
            "good.pdf": ("completed", None, None, None),
            "unsupported_bank.pdf": (
                "failed", "InvalidSchemaError",
                "415: Bank format not recognised. Supported formats: SCB, Co-op, ABSA",
                "request_parser",
            ),
            "empty_statement.pdf": (
                "failed", "InvalidSchemaError",
                "No valid transactions extracted via parity-ingestion",
                "request_parser",
            ),
            "wrong_currency.pdf": (
                "failed", "CurrencyMismatchError",
                "Statement currency USD does not match deal currency KES",
                "fix_currency",
            ),
        }

        def _ingest_side_effect(*, document_id, file_name, **kwargs):
            status, error_type, error_message, next_action = outcomes[file_name]
            if status == "completed":
                fake_docs_repo.mark_completed(document_id)
            else:
                fake_docs_repo.mark_failed(
                    document_id, error_type=error_type,
                    error_message=error_message, next_action=next_action,
                )
            return None  # real contract: never raises

        webhook_calls = []

        async def _fake_send_webhook(**kwargs):
            webhook_calls.append(kwargs)

        documents = [{"url": f"https://example.com/signed/{name}"} for name in outcomes]

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._download_file",
            AsyncMock(side_effect=_fake_download),
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            return_value=fake_docs_repo,
        ), patch(
            "v1.integrations.musa_file_processor.IngestionService.process_document_background",
            side_effect=_ingest_side_effect,
        ), patch(
            "v1.integrations.musa_file_processor._run_export",
            return_value={},
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ), patch(
            "v1.integrations.musa_file_processor._notify_parser_request",
            AsyncMock(),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-real-outcome",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",
                documents=documents,
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        complete_updates = [u for u in session_updates if u.get("status") == "complete"]
        assert len(complete_updates) == 1, "session should complete (1 real success out of 4)"
        assert "1 of 4 document(s) processed successfully" in (
            complete_updates[0].get("error_message") or ""
        ), complete_updates[0].get("error_message")

        assert len(webhook_calls) == 1
        assert webhook_calls[0]["status"] == "complete"

        assert len(parser_request_inserts) == 2, (
            "both request_parser-classified failures must each write their "
            "own parser_requests row"
        )
        pr_messages = {row["error_message"] for row in parser_request_inserts}
        assert pr_messages == {
            "415: Bank format not recognised. Supported formats: SCB, Co-op, ABSA",
            "No valid transactions extracted via parity-ingestion",
        }, "parser_requests rows must carry the real, distinct per-document reasons"

        doc_failures = complete_updates[0].get("document_failures")
        assert doc_failures is not None and len(doc_failures) == 3, doc_failures
        reasons = {f["error_message"] for f in doc_failures}
        assert reasons == {
            "415: Bank format not recognised. Supported formats: SCB, Co-op, ABSA",
            "No valid transactions extracted via parity-ingestion",
            "Statement currency USD does not match deal currency KES",
        }, f"expected 3 distinct real reasons, got: {reasons}"
        next_actions = {f["next_action"] for f in doc_failures}
        assert next_actions == {"request_parser", "fix_currency"}

    def test_all_documents_fail_for_distinct_reasons_session_gets_real_detail(self, monkeypatch):
        """
        The real-world shape from the June session (PAR-174/PAR-200): every
        document fails, none raise, and the reasons are genuinely
        different. Historically this collapsed into ONE generic
        "No transactions for deal ... ingestion may have failed" message
        with the real per-file reasons discarded. The fix must surface the
        real, distinct reasons on the session record — additively, during
        the 24h SLA window — even when nothing succeeds and PAR-62's
        deferred-webhook timing stays unchanged.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import process_musa_session

        mock_supabase, session_updates, parser_request_inserts = self._mock_supabase()
        fake_docs_repo = _FakeDocsRepo()

        async def _fake_download(url, timeout=300):
            return b"raw-bytes"

        outcomes = {
            "not_a_bank_statement.pdf": (
                "InvalidSchemaError",
                "415: Bank format not recognised. Supported formats: SCB, Co-op, ABSA",
                "request_parser",
            ),
            "unsupported_bank.pdf": (
                "InvalidSchemaError",
                "415: Bank format not recognised by parity-ingestion.",
                "request_parser",
            ),
            "empty_statement.pdf": (
                "InvalidSchemaError",
                "No valid transactions extracted via parity-ingestion",
                "request_parser",
            ),
        }

        def _ingest_side_effect(*, document_id, file_name, **kwargs):
            error_type, error_message, next_action = outcomes[file_name]
            fake_docs_repo.mark_failed(
                document_id, error_type=error_type,
                error_message=error_message, next_action=next_action,
            )
            return None

        webhook_calls = []

        async def _fake_send_webhook(**kwargs):
            webhook_calls.append(kwargs)

        documents = [{"url": f"https://example.com/signed/{name}"} for name in outcomes]

        with patch(
            "v1.integrations.musa_file_processor.get_supabase",
            return_value=mock_supabase,
        ), patch(
            "v1.db.supabase_repositories.get_supabase",
            return_value=MagicMock(),
        ), patch(
            "v1.integrations.musa_file_processor._download_file",
            AsyncMock(side_effect=_fake_download),
        ), patch(
            "v1.integrations.musa_file_processor.DocumentsRepo",
            return_value=fake_docs_repo,
        ), patch(
            "v1.integrations.musa_file_processor.IngestionService.process_document_background",
            side_effect=_ingest_side_effect,
        ), patch(
            "v1.integrations.musa_file_processor._send_webhook",
            AsyncMock(side_effect=_fake_send_webhook),
        ), patch(
            "v1.integrations.musa_file_processor._notify_parser_request",
            AsyncMock(),
        ):
            asyncio.run(process_musa_session(
                session_id="test-sid-all-fail-distinct",
                deal_id=str(uuid.uuid4()),
                venture_name="Acme",
                venture_country="Kenya",
                documents=documents,
                status_url="https://parity.io/status",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        # All 3 are request_parser-classified -> deferred to the 24h SLA
        # sweep, no immediate webhook or failed status (PAR-62, unchanged).
        assert webhook_calls == []
        assert not any(u.get("status") == "failed" for u in session_updates)
        assert len(parser_request_inserts) == 3

        detail_updates = [u for u in session_updates if u.get("document_failures")]
        assert len(detail_updates) == 1
        doc_failures = detail_updates[0]["document_failures"]
        assert len(doc_failures) == 3
        reasons = {f["error_message"] for f in doc_failures}
        assert reasons == {
            "415: Bank format not recognised. Supported formats: SCB, Co-op, ABSA",
            "415: Bank format not recognised by parity-ingestion.",
            "No valid transactions extracted via parity-ingestion",
        }, f"expected 3 distinct real reasons, got: {reasons}"

# ===========================================================================
# 7. POST/GET shape parity (structural)
# ===========================================================================

class TestShapeParity:
    """
    The fields returned by POST /sessions and GET /sessions/{id}/status
    must be identical — same keys, same types.
    """

    def test_create_and_status_return_identical_field_sets(self, client, monkeypatch):
        sid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Patch auth
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: True)

        # Patch for POST
        monkeypatch.setattr(
            "v1.integrations.musa_api.DealsRepo",
            lambda: MagicMock(create_deal=lambda d: {**d, "id": did}),
        )
        mock_sb_post = MagicMock()
        mock_sb_post.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"session_id": sid, "created_at": now}]
        )
        monkeypatch.setattr("v1.integrations.musa_api.get_supabase", lambda: mock_sb_post)
        monkeypatch.setattr("v1.integrations.musa_api.process_musa_session", lambda **kw: None)

        post_resp = client.post("/api/musa/sessions", json=VALID_SESSION_BODY, headers=VALID_HEADERS)
        assert post_resp.status_code == 200
        post_keys = set(post_resp.json().keys())

        # Patch for GET /status
        mock_sb_get = MagicMock()
        mock_sb_get.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[_fake_session_row(sid, deal_id=did)]
        )
        monkeypatch.setattr("v1.integrations.musa_api.get_supabase", lambda: mock_sb_get)

        get_resp = client.get(f"/api/musa/sessions/{sid}/status", headers=VALID_HEADERS)
        assert get_resp.status_code == 200
        get_keys = set(get_resp.json().keys())

        assert post_keys == get_keys, (
            f"Shape mismatch — POST has {post_keys - get_keys} extra, "
            f"GET has {get_keys - post_keys} extra"
        )



# ===========================================================================
# 6e. Raw-document retention cleanup (PAR-248)
# ===========================================================================

class TestParserRequestRetentionCleanup:
    def _row(self, status, requested_at, storage_path="musa/sid/file.pdf"):
        return {
            "id": str(uuid.uuid4()),
            "partner": "musa",
            "status": status,
            "storage_path": storage_path,
            "requested_at": requested_at,
        }

    def test_deletes_storage_for_expired_rows_past_retention_window(self):
        """
        _cleanup_expired_raw_documents must delete the storage file and clear
        storage_path for expired/resolved rows older than the retention window.
        """
        from v1.integrations.musa_parser_request_sla import _cleanup_expired_raw_documents

        old_expired = self._row(
            status="expired",
            requested_at=(datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            storage_path="musa/old-sid/old.pdf",
        )
        old_resolved = self._row(
            status="resolved",
            requested_at=(datetime.now(timezone.utc) - timedelta(days=6)).isoformat(),
            storage_path="musa/old-sid2/old2.pdf",
        )
        recent = self._row(
            status="expired",
            requested_at=(datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
            storage_path="musa/recent-sid/recent.pdf",
        )

        deleted_files = []

        def _fake_remove(paths):
            deleted_files.extend(paths)
            return MagicMock()

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.in_.return_value.lt.return_value.execute.return_value = MagicMock(
            data=[old_expired, old_resolved, recent]
        )
        mock_supabase.storage.from_.return_value.remove.side_effect = _fake_remove
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with patch(
            "v1.integrations.musa_parser_request_sla._RETENTION_DAYS",
            4,
        ):
            count = _cleanup_expired_raw_documents(mock_supabase)

        assert count == 2, f"Expected 2 deletions, got {count}"
        assert "musa/old-sid/old.pdf" in deleted_files
        assert "musa/old-sid2/old2.pdf" in deleted_files
        assert "musa/recent-sid/recent.pdf" not in deleted_files

    def test_pending_rows_never_deleted_by_retention_cleanup(self):
        """
        Rows with status="pending" must not be touched by the retention cleanup
        — they are still within the SLA window and the file may still be needed
        for an in-window retry.
        """
        from v1.integrations.musa_parser_request_sla import _cleanup_expired_raw_documents

        # Query returns no rows (status filter for expired/resolved applied in SQL)
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.in_.return_value.lt.return_value.execute.return_value = MagicMock(
            data=[]
        )

        count = _cleanup_expired_raw_documents(mock_supabase)

        assert count == 0
        mock_supabase.storage.from_.return_value.remove.assert_not_called()

    def test_force_close_does_not_delete_storage_file(self):
        """
        _force_close_expired (the SLA sweep's 24h force-close path) must NOT
        delete the storage file. Retention cleanup runs separately on its own
        schedule (PARSER_REQUEST_RETENTION_DAYS, default 10 days), so the file
        must still be present immediately after force-close for potential
        out-of-band recovery.
        """
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations import musa_parser_request_sla as sla

        expired_row = {
            "id": str(uuid.uuid4()),
            "partner": "musa",
            "status": "expired",
            "storage_path": "musa/sid/file.pdf",
            "requested_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
            "session_id": "sid-force-close",
            "deal_id": str(uuid.uuid4()),
        }
        session_row = {
            "session_id": "sid-force-close",
            "venture_name": "Acme",
            "venture_country": "Kenya",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        def _fake_table(name):
            tbl = MagicMock()
            if name == "musa_sessions":
                tbl.select.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[session_row]
                )
                tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            else:
                tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            return tbl

        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = _fake_table

        with patch(
            "v1.integrations.musa_parser_request_sla._send_webhook",
            AsyncMock(),
        ):
            asyncio.run(sla._force_close_expired(mock_supabase, expired_row))

        mock_supabase.storage.from_.return_value.remove.assert_not_called()


# ===========================================================================
# 8. Admin webhook resend (PAR-174 Phase 1)
# ===========================================================================

class TestAdminResendWebhookAuth:
    """POST /api/musa/admin/sessions/{id}/resend-webhook auth gate."""

    def test_no_credentials_returns_401(self, client):
        resp = client.post("/api/musa/admin/sessions/some-sid/resend-webhook")
        assert resp.status_code == 401

    def test_musa_partner_key_is_rejected(self, client, monkeypatch):
        # A valid Musa key must NOT satisfy the admin gate — Musa should not
        # be able to self-trigger resends of its own webhooks.
        monkeypatch.setattr("v1.integrations.auth.validate_api_key", lambda k, p: True)
        monkeypatch.setattr("v1.integrations.musa_api.validate_scoped_api_key", lambda k, t: False)
        resp = client.post(
            "/api/musa/admin/sessions/some-sid/resend-webhook",
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 401

    def test_admin_scoped_key_is_accepted(self, client, monkeypatch):
        monkeypatch.setattr("v1.integrations.musa_api.validate_scoped_api_key", lambda k, t: t == "admin")

        async def _fake_resend(session_id, base_url=None):
            return {
                "session_id": session_id,
                "status": "complete",
                "is_retry": True,
                "resend_count": 1,
                "webhook_status_code": 200,
                "webhook_delivered": True,
            }

        monkeypatch.setattr("v1.integrations.musa_api.resend_webhook_for_session", _fake_resend)
        resp = client.post(
            "/api/musa/admin/sessions/some-sid/resend-webhook",
            headers={"x-api-key": "admin-key"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_retry"] is True
        assert body["resend_count"] == 1


class TestResendWebhookForSession:
    """Unit tests for musa_file_processor.resend_webhook_for_session."""

    def _mock_supabase_for(self, session_row: Dict[str, Any], refreshed_row: Optional[Dict[str, Any]] = None):
        mock_sb = MagicMock()
        select_mock = mock_sb.table.return_value.select.return_value.eq.return_value.execute
        # First select = session lookup, second select (post-send) = refreshed delivery columns.
        select_mock.side_effect = [
            MagicMock(data=[session_row]),
            MagicMock(data=[refreshed_row or {}]),
        ]
        return mock_sb

    def test_404_when_session_not_found(self, monkeypatch):
        import asyncio
        from v1.integrations.musa_file_processor import resend_webhook_for_session

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        monkeypatch.setattr("v1.integrations.musa_file_processor.get_supabase", lambda: mock_sb)

        with pytest.raises(Exception) as exc_info:
            asyncio.run(resend_webhook_for_session("missing-sid"))
        assert getattr(exc_info.value, "status_code", None) == 404

    def test_409_when_session_still_processing(self, monkeypatch):
        import asyncio
        from v1.integrations.musa_file_processor import resend_webhook_for_session

        row = _fake_session_row("sid-1", status="processing")
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[row])
        monkeypatch.setattr("v1.integrations.musa_file_processor.get_supabase", lambda: mock_sb)

        with pytest.raises(Exception) as exc_info:
            asyncio.run(resend_webhook_for_session("sid-1"))
        assert getattr(exc_info.value, "status_code", None) == 409

    def test_completed_session_resend_marks_is_retry_and_increments_count(self, monkeypatch):
        """A COMPLETE session with no prior resends → resend_count goes to 1,
        and _send_webhook is called with is_retry=True."""
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import resend_webhook_for_session

        row = _fake_session_row("sid-2", status="complete", deal_id="deal-2")
        row["webhook_resend_count"] = 0
        mock_sb = self._mock_supabase_for(
            row,
            refreshed_row={
                "webhook_last_status_code": 200,
                "webhook_delivered_at": "2026-01-01T00:00:00+00:00",
                "webhook_resend_count": 1,
            },
        )
        monkeypatch.setattr("v1.integrations.musa_file_processor.get_supabase", lambda: mock_sb)

        fake_send = AsyncMock()
        monkeypatch.setattr("v1.integrations.musa_file_processor._send_webhook", fake_send)

        result = asyncio.run(resend_webhook_for_session("sid-2", base_url="https://api.example.com"))

        assert fake_send.called
        call_kwargs = fake_send.call_args.kwargs
        assert call_kwargs["is_retry"] is True
        assert call_kwargs["resend_count"] == 1

        assert result["is_retry"] is True
        assert result["resend_count"] == 1
        assert result["webhook_delivered"] is True

    def test_already_delivered_session_can_still_be_resent(self, monkeypatch):
        """Decision (PAR-174): resending a session whose webhook already
        succeeded is ALLOWED, not blocked — the is_retry/resend_count
        fields make it safe on Musa's side, and an admin explicitly
        choosing to resend is a deliberate action."""
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import resend_webhook_for_session

        row = _fake_session_row("sid-3", status="complete", deal_id="deal-3")
        row["webhook_resend_count"] = 2
        row["webhook_delivered_at"] = "2026-01-01T00:00:00+00:00"  # already delivered once
        mock_sb = self._mock_supabase_for(
            row,
            refreshed_row={
                "webhook_last_status_code": 200,
                "webhook_delivered_at": "2026-01-02T00:00:00+00:00",
                "webhook_resend_count": 3,
            },
        )
        monkeypatch.setattr("v1.integrations.musa_file_processor.get_supabase", lambda: mock_sb)
        fake_send = AsyncMock()
        monkeypatch.setattr("v1.integrations.musa_file_processor._send_webhook", fake_send)

        result = asyncio.run(resend_webhook_for_session("sid-3"))

        assert result["resend_count"] == 3  # continues counting from prior resends
        call_kwargs = fake_send.call_args.kwargs
        assert call_kwargs["is_retry"] is True
        assert call_kwargs["resend_count"] == 3

    def test_failed_session_resends_failed_status_without_pdf_url(self, monkeypatch):
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import resend_webhook_for_session

        row = _fake_session_row("sid-4", status="failed", deal_id="deal-4", error_message="boom")
        row["webhook_resend_count"] = 0
        mock_sb = self._mock_supabase_for(row, refreshed_row={"webhook_resend_count": 1})
        monkeypatch.setattr("v1.integrations.musa_file_processor.get_supabase", lambda: mock_sb)
        fake_send = AsyncMock()
        monkeypatch.setattr("v1.integrations.musa_file_processor._send_webhook", fake_send)

        asyncio.run(resend_webhook_for_session("sid-4"))

        call_kwargs = fake_send.call_args.kwargs
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["pdf_url"] is None
        assert call_kwargs["error_message"] == "boom"


class TestSendWebhookIdempotencyFieldsAndPersistence:
    def test_payload_includes_is_retry_and_resend_count(self, monkeypatch):
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import _send_webhook

        monkeypatch.setenv("MUSA_WEBHOOK_URL", "https://webhook.example.com")
        monkeypatch.setenv("MUSA_WEBHOOK_AUTH_TOKEN", "tok_test")

        mock_response = MagicMock(status_code=200)
        mock_post = AsyncMock(return_value=mock_response)
        mock_client_instance = AsyncMock()
        mock_client_instance.post = mock_post
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        mock_sb = MagicMock()
        monkeypatch.setattr("v1.integrations.musa_file_processor.get_supabase", lambda: mock_sb)

        with patch("v1.integrations.musa_file_processor.httpx.AsyncClient",
                   return_value=mock_client_instance):
            asyncio.run(_send_webhook(
                session_id="sid-retry",
                venture_name="Acme",
                venture_country="Kenya",
                status="complete",
                status_url="https://parity.io/status",
                pdf_url="https://parity.io/pdf",
                is_retry=True,
                resend_count=2,
            ))

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[1]
        assert payload["is_retry"] is True
        assert payload["resend_count"] == 2

        # Persistence: original-send calls (is_retry=False) must NOT touch
        # webhook_resend_count; this retry call must.
        update_call = mock_sb.table.return_value.update.call_args
        update_fields = update_call.args[0]
        assert update_fields["webhook_last_status_code"] == 200
        assert update_fields["webhook_resend_count"] == 2
        assert "webhook_delivered_at" in update_fields  # 200 → delivered timestamp set

    def test_original_send_does_not_touch_resend_count(self, monkeypatch):
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import _send_webhook

        monkeypatch.setenv("MUSA_WEBHOOK_URL", "https://webhook.example.com")
        monkeypatch.setenv("MUSA_WEBHOOK_AUTH_TOKEN", "tok_test")

        mock_response = MagicMock(status_code=500, text="server error")
        mock_post = AsyncMock(return_value=mock_response)
        mock_client_instance = AsyncMock()
        mock_client_instance.post = mock_post
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        mock_sb = MagicMock()
        monkeypatch.setattr("v1.integrations.musa_file_processor.get_supabase", lambda: mock_sb)

        with patch("v1.integrations.musa_file_processor.httpx.AsyncClient",
                   return_value=mock_client_instance):
            asyncio.run(_send_webhook(
                session_id="sid-original",
                venture_name="Acme",
                venture_country="Kenya",
                status="failed",
                status_url="https://parity.io/status",
                error_message="boom",
            ))

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[1]
        assert payload["is_retry"] is False
        assert payload["resend_count"] == 0

        update_fields = mock_sb.table.return_value.update.call_args.args[0]
        assert "webhook_resend_count" not in update_fields
        assert update_fields["webhook_last_status_code"] == 500
        assert "webhook_delivered_at" not in update_fields  # non-200 → not delivered

    # -- PAR-174 follow-up: webhook_first_delivered_at ----------------------
    #
    # webhook_delivered_at intentionally tracks the MOST RECENT success (see
    # test_payload_includes_is_retry_and_resend_count above, which pins that).
    # webhook_first_delivered_at is the separate, write-once audit fact.

    class _FakeSessionsTable:
        """Minimal postgrest stand-in that actually honours .eq()/.is_().

        The once-only behaviour is enforced by a DB-side filter, so asserting
        on mock call internals alone would not prove it. This applies the
        filters to a real dict row, so the test fails if the guard is dropped.
        """

        def __init__(self, row):
            self.row = row
            self._pending = {}
            self._filters = []

        def table(self, _name):
            return self

        def update(self, fields):
            self._pending = dict(fields)
            self._filters = []
            return self

        def eq(self, col, val):
            self._filters.append(("eq", col, val))
            return self

        def is_(self, col, val):
            self._filters.append(("is", col, val))
            return self

        def execute(self):
            for kind, col, val in self._filters:
                if kind == "eq" and self.row.get(col) != val:
                    return self
                if kind == "is" and val == "null" and self.row.get(col) is not None:
                    return self
            self.row.update(self._pending)
            return self

    def _run_send(self, monkeypatch, sb, status_code, session_id="sid-fd"):
        import asyncio
        from unittest.mock import AsyncMock
        from v1.integrations.musa_file_processor import _send_webhook

        monkeypatch.setenv("MUSA_WEBHOOK_URL", "https://webhook.example.com")
        monkeypatch.setenv("MUSA_WEBHOOK_AUTH_TOKEN", "tok_test")

        mock_response = MagicMock(status_code=status_code, text="")
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("v1.integrations.musa_file_processor.get_supabase", lambda: sb)
        with patch("v1.integrations.musa_file_processor.httpx.AsyncClient",
                   return_value=mock_client_instance):
            asyncio.run(_send_webhook(
                session_id=session_id,
                venture_name="Acme",
                venture_country="Kenya",
                status="complete",
                status_url="https://parity.io/status",
                pdf_url="https://parity.io/pdf",
            ))

    def test_first_success_stamps_first_delivered_at(self, monkeypatch):
        sb = self._FakeSessionsTable({
            "session_id": "sid-fd",
            "webhook_delivered_at": None,
            "webhook_first_delivered_at": None,
        })
        self._run_send(monkeypatch, sb, 200)

        assert sb.row["webhook_first_delivered_at"] is not None
        # First success: both columns describe the same moment.
        assert sb.row["webhook_first_delivered_at"] == sb.row["webhook_delivered_at"]

    def test_resend_advances_delivered_at_but_never_first_delivered_at(self, monkeypatch):
        """The actual regression guard for PAR-174's audit-history gap."""
        sb = self._FakeSessionsTable({
            "session_id": "sid-fd",
            "webhook_delivered_at": None,
            "webhook_first_delivered_at": None,
        })
        self._run_send(monkeypatch, sb, 200)
        first = sb.row["webhook_first_delivered_at"]
        original_delivered = sb.row["webhook_delivered_at"]
        assert first is not None

        self._run_send(monkeypatch, sb, 200)

        # webhook_delivered_at still moves — existing behaviour preserved.
        assert sb.row["webhook_delivered_at"] != original_delivered
        # ...but the original delivery time survives the resend. Without the
        # null guard this would have been overwritten, which is exactly the
        # data loss found on session 2847fbf0 on 2026-08-26.
        assert sb.row["webhook_first_delivered_at"] == first

    def test_failed_delivery_does_not_stamp_first_delivered_at(self, monkeypatch):
        sb = self._FakeSessionsTable({
            "session_id": "sid-fd",
            "webhook_delivered_at": None,
            "webhook_first_delivered_at": None,
        })
        self._run_send(monkeypatch, sb, 500)

        assert sb.row["webhook_first_delivered_at"] is None
        assert sb.row["webhook_delivered_at"] is None

    def test_first_delivered_write_is_guarded_and_separate_from_outcome_write(self, monkeypatch):
        """The once-only write must be its own null-filtered statement, and
        must never leak into the main outcome update (which is unconditional
        and would overwrite on every resend)."""
        mock_sb = MagicMock()
        self._run_send(monkeypatch, mock_sb, 200)

        update_calls = mock_sb.table.return_value.update.call_args_list
        assert len(update_calls) == 2
        assert "webhook_first_delivered_at" in update_calls[0].args[0]
        # The outcome write is last and must not carry the first-delivered key.
        outcome_fields = update_calls[1].args[0]
        assert "webhook_first_delivered_at" not in outcome_fields
        assert outcome_fields["webhook_delivered_at"] is not None

        is_call = mock_sb.table.return_value.update.return_value.eq.return_value.is_.call_args
        assert is_call.args == ("webhook_first_delivered_at", "null")
