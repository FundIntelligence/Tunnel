"""
Usage-tracking glue between require_scoped_api_key and PAR-130's
increment_api_key_usage() RPC.

require_scoped_api_key (backend/v1/integrations/auth.py) only proves *some*
active sandbox-classify key matches — it deliberately returns a bool, not a
row, and PAR-131 keeps that signature untouched. Metering needs the specific
row id, so this re-scans the same active/key_type rows and reuses the
existing _bcrypt_match primitive rather than re-implementing bcrypt
comparison here.
"""
from typing import Optional

from . import backend_path  # noqa: F401  (import order matters: sys.path must be patched first)
from v1.db.supabase_client import get_supabase
from v1.integrations.auth import _bcrypt_match


def find_active_key_row(api_key: str, key_type: str) -> Optional[dict]:
    supabase = get_supabase()
    result = (
        supabase.table("api_keys")
        .select("id, api_key_hash")
        .eq("key_type", key_type)
        .eq("active", True)
        .execute()
    )
    for row in result.data or []:
        if _bcrypt_match(api_key, [row["api_key_hash"]]):
            return row
    return None


def increment_usage_or_none(key_id: str) -> Optional[dict]:
    """Returns the updated api_keys row, or None if the RPC's UPDATE matched
    no row — i.e. the key was revoked or is already at call_cap (PAR-130's
    NULL-row-on-guard-failure: the guard is in the UPDATE's WHERE clause, so a
    failed guard is indistinguishable from "no such row" and must be treated
    as a hard rejection, not silently ignored)."""
    supabase = get_supabase()
    result = supabase.rpc("increment_api_key_usage", {"p_key_id": key_id}).execute()
    rows = result.data or []
    if isinstance(rows, list):
        return rows[0] if rows else None
    return rows or None
