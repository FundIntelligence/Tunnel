"""
PAR-245 — sandbox-classify lifetime call cap (3,000), atomic via
increment_api_key_usage() (migration 027/032, PAR-130/132).

Rule 9 note: PAR-245's own "no limit currently exists" claim was verified
independently before writing any of this (grep across backend/ for any
counter/limit logic came back empty, both in this ticket's own text and
reproduced here) -- but the underlying atomic mechanism (api_keys.calls_used/
call_cap + increment_api_key_usage()) already existed, unused, from
PAR-130/132/migration 032. This suite covers the new wiring in
require_scoped_api_key that's the first real caller of that mechanism, not
a reimplementation of it.

Off-by-one semantics (the exact SQL guard, unchanged from migration 027):
    UPDATE api_keys SET calls_used = calls_used + 1
    WHERE id = :id AND status = 'active' AND calls_used < call_cap
    RETURNING *;
A row is only returned (call allowed) when the PRE-increment calls_used is
strictly less than call_cap. With call_cap=3000: the call that brings
calls_used from 2999 -> 3000 succeeds (the 3000th call is allowed); the next
call, with calls_used already at 3000, is rejected (2999 < 3000 vs.
3000 < 3000). So exactly 3,000 calls succeed, and the request that would be
the 3,001st is the one rejected -- not 2,999, not 3,001. Confirmed by
re-deriving the SQL guard's own boundary condition (this session's Supabase
MCP connection is read-only, so a live end-to-end row-level test against
paritystaging was not possible from this session -- noted, not silently
skipped); the tests below verify this project's Python wiring interprets
that RPC boundary correctly, since the SQL guarantee itself is unchanged,
pre-existing, and already covered by 027/032's own history.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

import bcrypt

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from v1.integrations import auth
from v1.config import SANDBOX_FREE_LIMIT_CALLS


def _hash(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


class TestFindScopedKeyId(unittest.TestCase):
    def test_returns_matching_row_id(self):
        raw_key = "sandbox-secret"
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "key-123", "api_key_hash": _hash(raw_key)},
        ]
        self._patch(mock_sb)
        self.assertEqual(auth._find_scoped_key_id(raw_key, "sandbox-classify"), "key-123")

    def test_returns_none_when_no_match(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "key-123", "api_key_hash": _hash("something-else")},
        ]
        self._patch(mock_sb)
        self.assertIsNone(auth._find_scoped_key_id("wrong-key", "sandbox-classify"))

    def test_returns_none_and_swallows_exception_on_db_error(self):
        def _raise():
            raise RuntimeError("db unreachable")
        auth_get_supabase_backup = auth.get_supabase
        auth.get_supabase = _raise
        try:
            self.assertIsNone(auth._find_scoped_key_id("any", "sandbox-classify"))
        finally:
            auth.get_supabase = auth_get_supabase_backup

    def _patch(self, mock_sb):
        auth_get_supabase_backup = auth.get_supabase
        auth.get_supabase = lambda: mock_sb
        self.addCleanup(lambda: setattr(auth, "get_supabase", auth_get_supabase_backup))


class TestIncrementAndCheckUsage(unittest.TestCase):
    def test_returns_true_when_rpc_returns_a_row(self):
        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.return_value.data = [{"id": "key-123", "calls_used": 1}]
        self._patch(mock_sb)
        self.assertTrue(auth._increment_and_check_usage("key-123"))
        mock_sb.rpc.assert_called_once_with("increment_api_key_usage", {"p_key_id": "key-123"})

    def test_returns_false_when_rpc_returns_empty(self):
        """RPC returns [] (not a null-composite row -- migration 032's fix)
        when the WHERE guard excludes the row: cap reached or key revoked."""
        mock_sb = MagicMock()
        mock_sb.rpc.return_value.execute.return_value.data = []
        self._patch(mock_sb)
        self.assertFalse(auth._increment_and_check_usage("key-123"))

    def test_returns_false_and_swallows_exception_on_db_error(self):
        def _raise():
            raise RuntimeError("db unreachable")
        auth_get_supabase_backup = auth.get_supabase
        auth.get_supabase = _raise
        try:
            self.assertFalse(auth._increment_and_check_usage("key-123"))
        finally:
            auth.get_supabase = auth_get_supabase_backup

    def _patch(self, mock_sb):
        auth_get_supabase_backup = auth.get_supabase
        auth.get_supabase = lambda: mock_sb
        self.addCleanup(lambda: setattr(auth, "get_supabase", auth_get_supabase_backup))


class TestRequireScopedApiKeySandboxEnforcement(unittest.TestCase):
    """End-to-end through the FastAPI dependency, for the sandbox-classify
    key_type specifically."""

    def setUp(self):
        self.app = FastAPI()
        gate = auth.require_scoped_api_key("sandbox-classify")

        @self.app.get("/sandbox/ping")
        def _ping(_: bool = Depends(gate)):
            return {"ok": True}

        self.client = TestClient(self.app)

    def _patch(self, *, key_id, allowed):
        self.addCleanup(setattr, auth, "validate_scoped_api_key", auth.validate_scoped_api_key)
        self.addCleanup(setattr, auth, "_find_scoped_key_id", auth._find_scoped_key_id)
        self.addCleanup(setattr, auth, "_increment_and_check_usage", auth._increment_and_check_usage)
        auth.validate_scoped_api_key = lambda k, t: True
        auth._find_scoped_key_id = lambda k, t: key_id
        auth._increment_and_check_usage = lambda kid: allowed

    def test_call_under_the_limit_succeeds_and_increments(self):
        self._patch(key_id="key-123", allowed=True)
        resp = self.client.get("/sandbox/ping", headers={"x-api-key": "good"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})

    def test_call_that_would_cross_the_cap_is_rejected_with_403(self):
        self._patch(key_id="key-123", allowed=False)
        resp = self.client.get("/sandbox/ping", headers={"x-api-key": "good"})
        self.assertEqual(resp.status_code, 403)
        detail = resp.json()["detail"]
        self.assertIn(str(SANDBOX_FREE_LIMIT_CALLS), detail)
        self.assertIn("no further free sandbox calls", detail)

    def test_valid_key_but_id_lookup_fails_rejects_closed_not_open(self):
        """A real bcrypt match confirmed by validate_scoped_api_key, but the
        id lookup itself returning None (e.g. transient DB blip between the
        two calls) must reject, not silently let an unmetered call through."""
        self._patch(key_id=None, allowed=True)
        resp = self.client.get("/sandbox/ping", headers={"x-api-key": "good"})
        self.assertEqual(resp.status_code, 401)

    def test_invalid_key_never_reaches_the_increment_step(self):
        self.addCleanup(setattr, auth, "validate_scoped_api_key", auth.validate_scoped_api_key)
        self.addCleanup(setattr, auth, "_increment_and_check_usage", auth._increment_and_check_usage)
        auth.validate_scoped_api_key = lambda k, t: False
        calls = []
        auth._increment_and_check_usage = lambda kid: calls.append(kid) or True

        resp = self.client.get("/sandbox/ping", headers={"x-api-key": "bad"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(calls, [])  # never incremented for a key that never validated


class TestOtherKeyTypesUnaffected(unittest.TestCase):
    """PAR-245 scopes the cap to sandbox-classify only -- other key_type
    values sharing require_scoped_api_key (e.g. "admin", PAR-175) must not
    inherit a call cap they were never meant to have."""

    def test_admin_key_type_skips_increment_entirely(self):
        app = FastAPI()
        gate = auth.require_scoped_api_key("admin")

        @app.get("/admin/ping")
        def _ping(_: bool = Depends(gate)):
            return {"ok": True}

        client = TestClient(app)

        real_validate = auth.validate_scoped_api_key
        real_increment = auth._increment_and_check_usage
        auth.validate_scoped_api_key = lambda k, t: True
        calls = []
        auth._increment_and_check_usage = lambda kid: calls.append(kid) or False  # would reject if ever called
        try:
            resp = client.get("/admin/ping", headers={"x-api-key": "admin-key"})
        finally:
            auth.validate_scoped_api_key = real_validate
            auth._increment_and_check_usage = real_increment

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
