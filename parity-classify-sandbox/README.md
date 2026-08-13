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

This pass targets the already-provisioned `parity-staging` Supabase project
(`kstuensfekanfberjubz`) — migration 027 and `increment_api_key_usage()` are
already live there. The separate, pre-seeded isolated Supabase project
referenced in the PAR-132 decision doc (`kmgggdrpfsxtvyhjqncy`) could not be
confirmed: it doesn't appear in this Supabase account's project list and
`get_project` on it returns a bare permission error rather than a clear
not-found, for the second session in a row. It may exist under different
account credentials (PAR-58, the ticket that would have created it, is still
in Backlog / never started per Linear's own history) — if so, re-point
`SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` at it once someone with access to
that project can confirm it's the intended target.

## Local dev

```bash
cd parity-classify-sandbox
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... .venv/bin/uvicorn app.main:app --reload --port 8080
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
