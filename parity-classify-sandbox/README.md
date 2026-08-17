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
4. **Verified 2026-08-17** (once the Supabase connector was reconnected with
   ParityBenchmark authorized): `001_create_sandbox_api_keys.sql` is applied,
   `api_keys` matches PAR-130's schema exactly, RLS is genuinely active
   (`rowsecurity=true`), and the 5-test suite passes against real rows.
   `pg_policies` is empty for this table by design (service-role-only access
   — anon/authenticated get deny-all) — confirm with Weever this is the
   intended permanent posture before adding policies. Full detail on PAR-132.

**On the migration-apply mechanism** (PAR-164): this service's boot-time
migrator (`app/db/migrator.py`) was removed 2026-08-17, mirroring PAR-164's
fix on the main backend — it had the identical hang risk (`psycopg2.connect()`
with no `connect_timeout`, called in `lifespan()` before the app served
traffic; on the main backend this produced an indefinite hang against
Supabase's IPv6-only direct-connection host under Cloud Run's IPv4-only
egress, killed by the health check before anything logged).

**Unlike the main backend, PAR-142's CI-apply-on-merge gate
(`.github/workflows/apply-backend-migrations.yml`) does not cover this
service** — it only applies `backend/migrations/**.sql` to `parity-staging`.
Migration 001 was applied by hand this session (`apply_migration` against
`vksrelnjoejzqkiwqano`), not via any automated path. There is currently no
automated way to apply a future `migrations/*.sql` file in this directory —
that gap needs its own ticket (extend the PAR-142 workflow to this service's
migrations dir + `SANDBOX_DATABASE_URL`, or accept manual apply as the
permanent process) before adding a second migration file here.

## Env vars

| Var | Purpose |
|---|---|
| `SANDBOX_SUPABASE_URL` | ParitySandbox project URL — mapped onto the shared `SUPABASE_URL` inside this process only (`app/config.py`), so `v1.integrations.auth`/`v1.db.supabase_client` can be reused unmodified from `backend/` without touching that shared code or the main backend's own `SUPABASE_URL`. |
| `SANDBOX_SUPABASE_SERVICE_ROLE_KEY` | Same mapping, onto `SUPABASE_SERVICE_ROLE_KEY`. |

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
