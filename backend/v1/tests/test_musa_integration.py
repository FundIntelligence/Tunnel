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

        async def _fake_download(url, timeout=300):
            return b"raw-bytes"

        call_count = {"n": 0}

        def _ingest_side_effect(*, file_name, **kwargs):
            call_count["n"] += 1
            if "bad" in file_name:
                raise ValueError("Unsupported bank format — no recognisable transactions")
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
            return_value=MagicMock(),
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
