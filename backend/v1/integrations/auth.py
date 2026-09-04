import logging
from typing import Optional

import bcrypt
from fastapi import Header, HTTPException

from ..config import SANDBOX_FREE_LIMIT_CALLS
from ..db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def _bcrypt_match(api_key: str, hashes) -> bool:
    key_bytes = api_key.encode("utf-8")
    return any(bcrypt.checkpw(key_bytes, h.encode("utf-8")) for h in hashes)


def validate_api_key(api_key: str, partner_name: str) -> bool:
    try:
        supabase = get_supabase()
        result = (
            supabase.table("api_keys")
            .select("api_key_hash")
            .eq("partner_name", partner_name)
            .eq("active", True)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return False
        return _bcrypt_match(api_key, (row["api_key_hash"] for row in rows))
    except Exception:
        logger.exception("Error validating API key for partner %r", partner_name)
        return False


def validate_scoped_api_key(api_key: str, key_type: str) -> bool:
    """Same bcrypt-checked pattern as validate_api_key, keyed by api_keys.key_type
    instead of partner_name — the primitive musa-partner and sandbox-classify
    keys share (PAR-131)."""
    try:
        supabase = get_supabase()
        result = (
            supabase.table("api_keys")
            .select("api_key_hash")
            .eq("key_type", key_type)
            .eq("active", True)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return False
        return _bcrypt_match(api_key, (row["api_key_hash"] for row in rows))
    except Exception:
        logger.exception("Error validating API key for key_type %r", key_type)
        return False


def require_musa_api_key(x_api_key: str = Header(..., alias="x-api-key")) -> bool:
    if not validate_api_key(x_api_key, "Musa Ventures"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


def _find_scoped_key_id(api_key: str, key_type: str) -> Optional[str]:
    """Same bcrypt-checked lookup as validate_scoped_api_key, but returns the
    matched row's id instead of a bare bool -- needed to target the atomic
    increment_api_key_usage() RPC (PAR-130/032) at the specific key used,
    not just confirm *a* key of this key_type matched."""
    try:
        supabase = get_supabase()
        result = (
            supabase.table("api_keys")
            .select("id, api_key_hash")
            .eq("key_type", key_type)
            .eq("active", True)
            .execute()
        )
        rows = result.data or []
        key_bytes = api_key.encode("utf-8")
        for row in rows:
            if bcrypt.checkpw(key_bytes, row["api_key_hash"].encode("utf-8")):
                return row["id"]
        return None
    except Exception:
        logger.exception("Error resolving scoped API key id for key_type %r", key_type)
        return None


def _increment_and_check_usage(key_id: str) -> bool:
    """Atomic increment via increment_api_key_usage(p_key_id) (migration
    027/032): a single UPDATE ... WHERE calls_used < call_cap RETURNING *,
    so concurrent callers either land inside the cap or get nothing back --
    never a lost update / TOCTOU race between checking and incrementing.
    Returns True (and the row is now incremented) iff the call is allowed."""
    try:
        supabase = get_supabase()
        result = supabase.rpc("increment_api_key_usage", {"p_key_id": key_id}).execute()
        rows = result.data or []
        return len(rows) > 0
    except Exception:
        logger.exception("Error incrementing usage for api_keys.id=%r", key_id)
        return False


def require_scoped_api_key(key_type: str):
    """FastAPI dependency factory for non-Musa key types (e.g. sandbox-classify).
    Depends on api_keys.key_type (PAR-130's migration); require_musa_api_key
    above is untouched and keeps its own partner_name-based lookup.

    PAR-245: for key_type == "sandbox-classify" specifically, also enforces
    the atomic lifetime call cap (api_keys.call_cap, capped at
    SANDBOX_FREE_LIMIT_CALLS by migration 042) before the request is allowed
    through -- this runs as a FastAPI dependency, so it executes before the
    route handler body, satisfying "check before processing." Deliberately
    scoped to sandbox-classify only: other key_type values using this same
    factory (e.g. "admin", PAR-175/-required snapshot access) must not
    inherit a usage cap they were never meant to have.
    """

    def _dependency(x_api_key: str = Header(..., alias="x-api-key")) -> bool:
        if not validate_scoped_api_key(x_api_key, key_type):
            raise HTTPException(status_code=401, detail="Invalid API key")

        if key_type == "sandbox-classify":
            key_id = _find_scoped_key_id(x_api_key, key_type)
            if key_id is None:
                # validate_scoped_api_key already confirmed a bcrypt match
                # exists; a None here means the lookup itself failed (e.g.
                # a transient DB error) between those two calls -- fail
                # closed rather than let the request through unmetered.
                raise HTTPException(status_code=401, detail="Invalid API key")
            if not _increment_and_check_usage(key_id):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Sandbox call limit reached ({SANDBOX_FREE_LIMIT_CALLS} lifetime "
                        "calls used). This key has no further free sandbox calls."
                    ),
                )

        return True

    return _dependency
