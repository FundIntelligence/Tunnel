# Async PDF generation — implementation plan (scoping only, no code written)

**Scope:** Uzo's issue — `/v1/deals/{deal_id}/snapshot/pdf` times out for large deals.
**Status:** plan only. Nothing implemented. Decisions flagged, not taken unilaterally.

Established tonight, from prod logs and local measurement on the real Deed document
(`e81e1d22-…`, 3,059 txns):

- Uncontended prod render ≈ **90–100s**; confirmed by real 200s on 2026-08-17 at 95.2s and 105.6s.
- The 45s `_PDF_RENDER_TIMEOUT_S` sits below actual cost → SIGKILL → 503.
- Prod is ~9x slower than local per layout page on an *idle* instance. Not code, not
  template, not WeasyPrint version, not contention.

---

## 1. Existing patterns found (reuse these; do not invent new ones)

### 1a. The job/status pattern already exists — partly

`backend/v1/musa/api.py` implements exactly the target shape:

- `POST /sessions` → `status_code=202`, returns `session_id` + status
- `GET /sessions/{session_id}` → status row (`status`, `started_at`, `completed_at`, `error_message`)
- Backed by a `pds_musa_sessions` table

**Reuse the shape. Do NOT reuse its worker.** `backend/v1/musa/worker.py` defines
`musa_worker = MusaWorker(poll_interval=10)` and its docstring says it is "imported by
main.py" — it is **not**. `grep` for `musa_worker` outside its own file returns nothing,
and `backend/main.py`'s `lifespan` starts only `parser_request_sla_sweeper`. The polling
worker is dead code. Anyone reading it as a working precedent will be misled.

### 1b. The live background pattern is FastAPI `BackgroundTasks`

Three live usages, all the same shape — insert a row with a status, fire
`background_tasks.add_task(...)`, return immediately:

- `backend/v1/api.py:525` and `:645` → `ingestion.process_document_background`
- `backend/v1/integrations/musa_api.py:242` → `process_musa_session`, returning a `status_url`

Prod log evidence that these survive past the response: `[INGEST] stage=PARSE_START` at
`2026-08-18T14:02:29`, failing at `14:04:50` — **141s** of post-response execution.
Caveat in §2: that work is I/O-bound, which is not the same as CPU-bound.

### 1c. Deterministic-cache short-circuit

`backend/v1/api.py:1039–1076` already short-circuits export when the latest snapshot is
unchanged and `config_version` matches. Same idea applies here and is high-value: a
rendered PDF is deterministic for a given `(deal, snapshot_id, variant, config_version)`.
Caching turns a repeat 90s render into an instant hit.

### 1d. No object-storage pattern exists

There is no Supabase Storage / GCS usage in `backend/v1/`. `"documents"` is a DB table,
not a bucket. So a finished PDF has nowhere existing to live — see §3.

---

## 2. The load-bearing constraint: Cloud Run CPU throttling

Verified live config on `parity-backend-prod` (revision `00030-l9z`):

```
cpu: '4'   memory: 12Gi   containerConcurrency: 80   timeoutSeconds: 1200
autoscaling.knative.dev/maxScale: '3'
run.googleapis.com/startup-cpu-boost: 'true'
# no minScale               => min-instances 0
# no cpu-throttling: false  => CPU allocated during request processing ONLY
```

**This is the decision the whole design hangs on.** With default throttling, CPU outside
request processing is throttled to a small fraction. A naive `BackgroundTasks` render is
CPU-bound for ~90s of *full-CPU* work; throttled, that could stretch to many minutes or
effectively stall. The §1b evidence does not disprove this — that task was blocked on an
HTTP call to `parity-ingestion`, and network waits are not what throttling penalizes.

**This assumption must be tested before committing to an option.** A 20-minute spike —
enqueue a CPU-bound loop as a `BackgroundTask` on a staging revision and time it — settles
it definitively. Do that first; it selects between Option A and Option B below.

Second constraint from tonight's data: six overlapping renders measured **~4.6x**
degradation (95–105s isolated → 449–491s concurrent). Whatever executes renders must
**serialize them** (semaphore, or single-claim job locking), or async merely relocates the
timeout. This is not the `concurrency=80` ticket — it is a property of the new path.

---

## 3. Proposed design

### Storage

Deed's rendered PDF is **81,894 bytes**. Recommend storing bytes **in the job row**
(`bytea`, or base64 `text`) rather than standing up a new storage bucket. Reuses the
existing supabase-py table pattern, adds no new infra, no new IAM, no new failure mode.
Revisit only if enriched/report variants turn out materially larger.

### New table — migration `035_add_pdf_jobs.sql`

Migrations are append-only (`CLAUDE.md`); latest is `034_add_musa_webhook_delivery_tracking.sql`
(note: `033` is absent), so the next file is `035`. **New file, never edit an existing one.**

```
pds_pdf_jobs
  job_id            text primary key
  deal_id           text not null
  variant           text not null      -- snapshot | enriched | report
  params            jsonb              -- view, partner_name, enrichment_id
  status            text not null      -- pending | running | done | failed
  snapshot_id       text               -- for cache key + invalidation
  config_version    text               -- for cache key
  pdf_bytes         bytea              -- ~82KB typical
  error_message     text
  requested_by      text               -- for retrieval authorization
  created_at / started_at / completed_at   timestamptz
```

Needs an RLS policy consistent with `030_document_rls_no_policy_decisions.sql`.

### New endpoints (additive — existing sync endpoint untouched)

All three gated by the existing `_require_snapshot_access` (`api.py:398`):

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/v1/deals/{deal_id}/snapshot/pdf/jobs` | 202 + `{job_id, status, poll_url}`; returns existing `done` job if cache key matches |
| `GET` | `/v1/deals/{deal_id}/snapshot/pdf/jobs/{job_id}` | status JSON (mirrors `musa/api.py:95`) |
| `GET` | `/v1/deals/{deal_id}/snapshot/pdf/jobs/{job_id}/content` | PDF bytes when `done`; 409 while pending; 404 unknown |

Retrieval must verify the caller is entitled to *this* job, not merely authenticated.

### Execution — pick after the §2 spike

**Option A — `BackgroundTasks` + set `--no-cpu-throttling`**
Smallest code; directly reuses `add_task`. Requires one service-config change (CPU always
allocated), which increases billing from request-time to instance-lifetime. Job can still
be lost if the instance scales down mid-render → needs a stale-job reaper (`running` rows
older than N minutes → `failed`/requeue).

**Option B — Cloud Tasks self-POST to an internal render endpoint** *(more robust)*
Render executes *inside* a request, so full CPU is guaranteed and `timeoutSeconds: 1200`
applies — comfortably above the ~90s cost. Cloud Tasks provides retries and rate limiting
natively (which also solves serialization). Costs a queue, a service account, and OIDC auth
on the internal endpoint.

**Option C — Cloud Run Job / dedicated worker service.** Most robust, most infra. Overkill
for the stated scope.

**Recommendation:** Option B if the §2 spike confirms throttling bites; Option A if it does
not. Do not pick blind — the spike is cheap relative to building the wrong one.

The async path should carry its own render budget (e.g. 300–600s) while the sync path keeps
`_PDF_RENDER_TIMEOUT_S = 45` unchanged.

---

## 4. Threshold decision (asked for explicitly)

**Recommend: additive opt-in. Always async on the new endpoints; leave the existing sync
endpoint's behavior exactly as-is.**

Rejected alternative — auto-detect by transaction count and route within the existing
endpoint:

- The count is only known *after* part of the ~9.3s DB phase, so the decision is late.
- It makes one URL return either `200 + PDF` or `202 + job` depending on data volume —
  a contract change on a working endpoint, and the harder thing to test correctly.
- The threshold itself becomes a tuning parameter nobody can set confidently.

**Tradeoff, stated plainly:** opt-in means Uzo must change their integration to call the
new endpoints. If that is unacceptable, the middle path is a query flag (`?async=1`) on the
existing URL — still explicit, same routing logic, no silent behavior change. What I'd
avoid is implicit auto-routing.

---

## 5. Rough size

| Item | Size |
|---|---|
| Migration `035` + RLS | S |
| Job table repo access | S–M (~100 LOC) |
| 3 endpoints | M (~120 LOC) |
| Render task fn (reuses `render_snapshot_html` + `_render_html_to_pdf`) | S–M (~80 LOC) |
| Cache short-circuit (reuses `api.py:1039` idea) | S |
| Serialization + stale-job reaper | M |
| Option B only: queue, SA, OIDC | M–L |
| Tests (`backend/tests_v1` conventions) | M |

**Option A ≈ 1–2 days. Option B ≈ 2–4 days** including infra. Plus the §2 spike (~half day)
which gates the choice.

**Deterministic-rules audit (per `CLAUDE.md`):** no changes to `backend/v1/core/` or
`backend/v1/parsing/`; no classifier, hash, coverage, confidence, or reconciliation logic
touched. `backend/migrations/` gains a *new* file only. Expected **PASS**, to be re-confirmed
against the actual diff at PR time.

---

## 6. Worth weighing before building any of this

`_PDF_RENDER_TIMEOUT_S = 45` → ~180s is a **one-line change** that would make Deed succeed
today. This is not speculation: the same document returned 200 at 95.2s and 105.6s on
2026-08-17 before the subprocess kill landed.

Costs of the one-liner: a ~90s synchronous client wait; one of 80 concurrency slots held for
that duration; and, under the measured 4.6x contention, concurrent requests could still
exceed even 180s. It is strictly worse than async as an end state.

But it is hours, not days, and it unblocks Uzo now. A reasonable sequencing is: ship the
timeout raise as the interim, then build async properly behind it. Flagging this because
"async is the root fix" and "async is what we should build first" are different claims, and
the second one is yours to decide, not mine.

---

## 7. Open questions

1. Can Uzo change their integration (decides §4)?
2. Is `--no-cpu-throttling` acceptable cost-wise (decides A vs B, alongside the spike)?
3. Should `/snapshot/pdf/enriched` and `/report` — the other two callers of
   `_render_html_to_pdf` (`api.py:1504`, `:1519`) — get the same treatment, or is this
   `snapshot/pdf` only for now?
4. Retention policy for `pds_pdf_jobs` rows and their stored bytes.
