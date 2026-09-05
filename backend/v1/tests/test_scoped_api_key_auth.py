"""
Tests for the generalized scope/key_type API key auth path (PAR-131).

Covers:
  - validate_scoped_api_key: bcrypt-checked lookup by key_type, mirroring
    validate_api_key's partner_name lookup
  - require_scoped_api_key: dependency factory raising 401 on a bad key
  - require_musa_api_key / validate_api_key are unchanged by the refactor

Run:
    cd backend
    python3 -m pytest v1/tests/test_scoped_api_key_auth.py -v
"""

import bcrypt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from v1.integrations import auth


def _hash(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


class TestValidateScopedApiKey:
    def test_valid_key_for_matching_key_type(self, monkeypatch):
        raw_key = "sandbox-secret"
        mock_sb = _mock_supabase_returning(monkeypatch, [{"api_key_hash": _hash(raw_key)}])
        assert auth.validate_scoped_api_key(raw_key, "sandbox-classify") is True
        mock_sb.table.assert_called_with("api_keys")

    def test_wrong_key_for_matching_key_type_fails(self, monkeypatch):
        _mock_supabase_returning(monkeypatch, [{"api_key_hash": _hash("sandbox-secret")}])
        assert auth.validate_scoped_api_key("wrong-key", "sandbox-classify") is False

    def test_no_rows_for_key_type_fails(self, monkeypatch):
        _mock_supabase_returning(monkeypatch, [])
        assert auth.validate_scoped_api_key("any-key", "sandbox-classify") is False

    def test_exception_is_swallowed_and_returns_false(self, monkeypatch):
        def _raise():
            raise RuntimeError("db unreachable")

        monkeypatch.setattr(auth, "get_supabase", _raise)
        assert auth.validate_scoped_api_key("any-key", "sandbox-classify") is False

    def test_filters_by_key_type_column_and_active(self, monkeypatch):
        raw_key = "sandbox-secret"
        mock_sb = _mock_supabase_returning(monkeypatch, [{"api_key_hash": _hash(raw_key)}])
        auth.validate_scoped_api_key(raw_key, "sandbox-classify")
        query = mock_sb.table.return_value.select.return_value
        query.eq.assert_any_call("key_type", "sandbox-classify")


class TestRequireScopedApiKey:
    """Generic dependency-factory mechanism -- deliberately NOT key_type
    "sandbox-classify" here (PAR-245 added sandbox-classify-specific call-cap
    enforcement inside require_scoped_api_key's dependency; that behavior has
    its own dedicated coverage in test_par245_sandbox_call_cap.py). Using a
    different key_type keeps this class testing the shared 401/200 gate
    mechanism in isolation, unaffected by that key_type-specific branch."""

    @pytest.fixture
    def client(self, monkeypatch):
        app = FastAPI()
        gate = auth.require_scoped_api_key("generic-scope")

        @app.get("/sandbox/ping")
        def _ping(_: bool = Depends(gate)):
            return {"ok": True}

        return TestClient(app)

    def test_missing_key_returns_422(self, client):
        resp = client.get("/sandbox/ping")
        assert resp.status_code == 422

    def test_invalid_key_returns_401(self, client, monkeypatch):
        monkeypatch.setattr(auth, "validate_scoped_api_key", lambda k, t: False)
        resp = client.get("/sandbox/ping", headers={"x-api-key": "wrong"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid API key"

    def test_valid_key_returns_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "validate_scoped_api_key", lambda k, t: True)
        resp = client.get("/sandbox/ping", headers={"x-api-key": "right"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_passes_key_type_through_to_validator(self, monkeypatch):
        seen = {}

        def _fake_validate(key, key_type):
            seen["key_type"] = key_type
            return True

        monkeypatch.setattr(auth, "validate_scoped_api_key", _fake_validate)
        app = FastAPI()

        @app.get("/ping")
        def _ping(_: bool = Depends(auth.require_scoped_api_key("sandbox-classify"))):
            return {"ok": True}

        TestClient(app).get("/ping", headers={"x-api-key": "k"})
        assert seen["key_type"] == "sandbox-classify"


class TestMusaPathUnchanged:
    """require_musa_api_key/validate_api_key must behave exactly as before —
    same signature, same partner_name query — after the _bcrypt_match
    extraction."""

    def test_validate_api_key_still_queries_by_partner_name(self, monkeypatch):
        raw_key = "musa-secret"
        mock_sb = _mock_supabase_returning(monkeypatch, [{"api_key_hash": _hash(raw_key)}])
        assert auth.validate_api_key(raw_key, "Musa Ventures") is True
        query = mock_sb.table.return_value.select.return_value
        query.eq.assert_any_call("partner_name", "Musa Ventures")

    def test_require_musa_api_key_rejects_bad_key(self, monkeypatch):
        monkeypatch.setattr(auth, "validate_api_key", lambda k, p: False)
        with pytest.raises(HTTPException) as exc_info:
            auth.require_musa_api_key(x_api_key="bad")
        assert exc_info.value.status_code == 401

    def test_require_musa_api_key_accepts_good_key(self, monkeypatch):
        monkeypatch.setattr(auth, "validate_api_key", lambda k, p: True)
        assert auth.require_musa_api_key(x_api_key="good") is True


def _mock_supabase_returning(monkeypatch, rows):
    from unittest.mock import MagicMock

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = rows
    monkeypatch.setattr(auth, "get_supabase", lambda: mock_sb)
    return mock_sb
