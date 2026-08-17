import logging

import bcrypt
from fastapi import Header, HTTPException

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


def require_scoped_api_key(key_type: str):
    """FastAPI dependency factory for non-Musa key types (e.g. sandbox-classify).
    Depends on api_keys.key_type (PAR-130's migration); require_musa_api_key
    above is untouched and keeps its own partner_name-based lookup."""

    def _dependency(x_api_key: str = Header(..., alias="x-api-key")) -> bool:
        if not validate_scoped_api_key(x_api_key, key_type):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return True

    return _dependency
