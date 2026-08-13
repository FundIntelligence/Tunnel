# Parity Classify Sandbox (PAR-132)

Isolated external service for sandbox/partner traffic. Wraps the existing
deterministic core engine (`backend/v1/core/classifier.py`) behind its own
auth/metering layer, deliberately kept off `api.py`'s route set so unproven
external callers can never degrade the main product — see the PAR-132
decision doc for the full rationale (Option B, decided over bolting onto
`api.py`).

## Endpoint

`POST /v1/classify` — the only route this service exposes. Auth: `x-api-key`
header, validated against `api_keys` where `key_type = 'sandbox-classify'`
(PAR-130/PAR-131). Each successful auth also calls `increment_api_key_usage()`
via RPC; a revoked key or one at `call_cap` gets `403`, not `401` — the key
itself is valid, it's just not allowed to spend another call.

Request:
```json
{
  "normalized_descriptor": "SALARY PAYMENT",
  "signed_amount_cents": 500000,
  "is_transfer": false,
  "large_positive_threshold_cents": null,
  "median_txn_abs_cents": null
}
```

Response:
```json
{ "role": "income", "classification_reason": "..." }
```

## Why this isn't a fork of backend/v1/core

`app/backend_path.py` puts the real `backend/` directory on `sys.path` at
import time instead of vendoring a copy of `classifier.py` /
`metrics_engine.py` / `v1/integrations/auth.py`. The Dockerfile's build
context is the repo root for the same reason — it `COPY`s the specific
`backend/v1/{core,integrations,db}` files this service actually imports
(not the rest of `v1/`, which it has no business touching) rather than
duplicating them. This keeps the sandbox and the main product's core engine
from drifting apart.

## Supabase project

**Current target: ParitySandbox (`vksrelnjoejzqkiwqano`)**, a dedicated
isolated project under the ParityBenchmark org — created by Weever to
replace both the unreachable `kmgggdrpfsxtvyhjqncy` (PAR-58's original,
never-confirmed reference) and the `parity-staging` substitution this
service ran against for one pass while that was unresolved.

**History, so this doesn't get re-litigated:**
1. PAR-132's decision doc named `kmgggdrpfsxtvyhjqncy` as already
   seeded/unused. Two sessions running confirmed it's not reachable under
   the connected Supabase account (`list_projects` doesn't show it,
   `get_project` returns a bare permission error) — and PAR-58, the ticket
   that would have created it, was still Backlog/never-started per Linear.
2. First pass of this PR substituted `parity-staging` (`kstuensfekanfberjubz`)
   as the target rather than block indefinitely, since migration 027 /
   `increment_api_key_usage()` were already live there.
3. Weever then provisioned `vksrelnjoejzqkiwqano` under ParityBenchmark for
   real, confirming this is the intended long-term isolated project — not
   a third substitution. **This service is wired to it now**, via its own
   `migrations/001_create_sandbox_api_keys.sql` (fresh table, RLS enabled
   at creation — not parity-staging's copy) and its own
   `SANDBOX_SUPABASE_URL`/`SANDBOX_SUPABASE_SERVICE_ROLE_KEY`/
   `SANDBOX_DATABASE_URL` env vars (see below) — `parity-staging` and the
   main backend are untouched by this change.
4. **Still unverified as of this writing** (Supabase MCP is connected to
   org "Parity" only — it cannot see ParityBenchmark/`vksrelnjoejzqkiwqano`
   at all, same org-scope gap as before, now confirmed against the new ref
   too): that the migration actually applies cleanly against a live
   `vksrelnjoejzqkiwqano`, that RLS is actually enabled once applied, and
   that the 5-test suite passes against real (not mocked) rows. Someone
   with MCP/dashboard access to ParityBenchmark needs to confirm these
   before this is production-ready — see PR discussion.

**On the migration-apply mechanism** (PAR-142, "CI-apply-on-merge"): that
ticket is still Backlog/unbuilt — there is no CI workflow in this repo that
applies `*.sql` migrations on merge, for either backend or this service.
The only mechanism that actually exists is the boot-time self-healing
migrator backend/ already uses (re-runs every `IF NOT EXISTS`-guarded file
on cold start); `app/db/migrator.py` mirrors that exactly, scoped to this
service's own `migrations/` dir and its own `SANDBOX_DATABASE_URL`. This
means the migration is applied by the service's own startup, not by a
human or agent running SQL by hand against the dashboard — but it is not
the CI-gated mechanism PAR-142 envisions, because that doesn't exist yet.
Worth raising back on PAR-142 itself.

## Env vars

| Var | Purpose |
|---|---|
| `SANDBOX_SUPABASE_URL` | ParitySandbox project URL — mapped onto the shared `SUPABASE_URL` inside this process only (`app/config.py`), so `v1.integrations.auth`/`v1.db.supabase_client` can be reused unmodified from `backend/` without touching that shared code or the main backend's own `SUPABASE_URL`. |
| `SANDBOX_SUPABASE_SERVICE_ROLE_KEY` | Same mapping, onto `SUPABASE_SERVICE_ROLE_KEY`. |
| `SANDBOX_DATABASE_URL` | Direct Postgres connection string for `app/db/migrator.py` (distinct from backend's `DATABASE_URL` on purpose). |

## Local dev

```bash
cd parity-classify-sandbox
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SANDBOX_SUPABASE_URL=... SANDBOX_SUPABASE_SERVICE_ROLE_KEY=... SANDBOX_DATABASE_URL=... \
  .venv/bin/uvicorn app.main:app --reload --port 8080
```

## Tests

```bash
cd parity-classify-sandbox
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -v
```

## Deploy

`cloudbuild-staging.yaml` — staging only for this pass, per PAR-132 scope.
No `cloudbuild-prod.yaml` yet; production is out of scope until the sandbox
has proven itself in staging.
