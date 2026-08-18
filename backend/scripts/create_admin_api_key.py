"""
One-time (or per-rotation) script to mint an "admin"-scoped API key.

PAR-175 added GET /v1/deals/{deal_id}/snapshot/pdf and .../snapshot/html
auth via _require_snapshot_access (v1/api.py), which accepts a Musa
partner key, an internal Supabase JWT, or an "admin"-scoped x-api-key
(api_keys.key_type = "admin"). The admin panel's server-side PDF proxy
(admin/app/api/data/deals/[dealId]/snapshot-pdf/route.ts) has no per-deal
user session to forward, so it authenticates with this key instead.

The raw key is printed ONCE and never stored — copy it into the admin
app's ADMIN_BACKEND_API_KEY env var immediately.

Run:
    cd backend
    python3 scripts/create_admin_api_key.py
"""
import secrets
import sys

import bcrypt

sys.path.insert(0, ".")
from v1.db.supabase_client import get_supabase  # noqa: E402

KEY_TYPE = "admin"


def main() -> None:
    raw_key = f"padm_{secrets.token_urlsafe(32)}"
    key_hash = bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    supabase = get_supabase()
    supabase.table("api_keys").insert({
        "api_key_hash": key_hash,
        "partner_name": "Admin Panel",
        "key_type": KEY_TYPE,
        "active": True,
    }).execute()

    print("Admin API key created. This is the ONLY time the raw key is shown:")
    print()
    print(f"  {raw_key}")
    print()
    print("Set this as ADMIN_BACKEND_API_KEY in the admin app's environment (Vercel).")


if __name__ == "__main__":
    main()
