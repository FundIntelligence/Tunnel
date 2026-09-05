"""
POST /v1/classify — PAR-132.

Covers the minimum required by the ticket: valid key succeeds, invalid key
rejected, revoked key rejected, at-cap key rejected. Revoked and at-cap are
separate tests (not just "invalid") because they take a different code
path: both pass the require_scoped_api_key gate (the row exists, active=True,
bcrypt matches) and only fail later at increment_api_key_usage's guarded
UPDATE, which returns no row for either case — PAR-130's
NULL-row-on-guard-failure behavior this ticket calls out explicitly.
"""
from tests.conftest import configure_key_row

_PAYLOAD = {
    "normalized_descriptor": "SALARY PAYMENT",
    "signed_amount_cents": 500000,
    "is_transfer": False,
}


def test_valid_key_succeeds(client, mock_supabase):
    configure_key_row(mock_supabase, raw_key="good-key", status="active", calls_used=0, call_cap=10)

    resp = client.post("/v1/classify", json=_PAYLOAD, headers={"x-api-key": "good-key"})

    assert resp.status_code == 200
    body = resp.json()
    assert "role" in body and "classification_reason" in body


def test_invalid_key_rejected(client, mock_supabase):
    configure_key_row(mock_supabase, raw_key="the-real-key", status="active", calls_used=0, call_cap=10)

    resp = client.post("/v1/classify", json=_PAYLOAD, headers={"x-api-key": "wrong-key"})

    assert resp.status_code == 401
    # Never reached the usage RPC for a key that failed the auth gate.
    mock_supabase.rpc.assert_not_called()


def test_missing_key_rejected(client, mock_supabase):
    resp = client.post("/v1/classify", json=_PAYLOAD)
    assert resp.status_code == 422


def test_revoked_key_rejected(client, mock_supabase):
    configure_key_row(mock_supabase, raw_key="revoked-key", status="revoked", calls_used=0, call_cap=10)

    resp = client.post("/v1/classify", json=_PAYLOAD, headers={"x-api-key": "revoked-key"})

    assert resp.status_code == 403


def test_at_cap_key_rejected(client, mock_supabase):
    configure_key_row(mock_supabase, raw_key="maxed-key", status="active", calls_used=10, call_cap=10)

    resp = client.post("/v1/classify", json=_PAYLOAD, headers={"x-api-key": "maxed-key"})

    assert resp.status_code == 403
