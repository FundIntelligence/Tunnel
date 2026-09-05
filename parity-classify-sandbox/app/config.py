"""
Env var isolation for this service's Supabase project (ParitySandbox,
vksrelnjoejzqkiwqano) — deliberately separate names from the main
backend's SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (which point at
parity-staging) so a Cloud Run misconfiguration can never make this
service and the main backend cross-reference each other's project.

v1.db.supabase_client.get_supabase() — reused unmodified from backend/,
per PAR-131 "reuse it, don't rebuild" — reads the generic SUPABASE_URL /
SUPABASE_SERVICE_ROLE_KEY names. Renaming those at the source would touch
shared backend code and affect the main backend too, which PAR-132's
follow-up explicitly rules out. Instead, this maps this service's own
SANDBOX_-prefixed vars onto the generic names, but only inside this
process's own environment — each Cloud Run service has its own isolated
container env, so this has no effect on the main backend's process.
"""
import os

_SANDBOX_TO_SHARED = {
    "SANDBOX_SUPABASE_URL": "SUPABASE_URL",
    "SANDBOX_SUPABASE_SERVICE_ROLE_KEY": "SUPABASE_SERVICE_ROLE_KEY",
}


def bootstrap_sandbox_supabase_env() -> None:
    for sandbox_name, shared_name in _SANDBOX_TO_SHARED.items():
        value = os.getenv(sandbox_name)
        if value:
            os.environ[shared_name] = value
