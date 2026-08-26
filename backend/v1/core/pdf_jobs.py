"""
PAR-192 — interim async PDF job bookkeeping + Cloud Run Job trigger.

Deliberately narrow and tactical, per PAR-192's scope: this wraps the
EXISTING, unchanged render path (render_snapshot_html() + _render_html_to_pdf(),
both untouched) in a background execution mechanism, off the synchronous
request path. It does not touch build_snapshot_context(), pdf_generator.py,
or any financial-value computation. Expected to be replaced by PAR-191's
hash-based freshness-policy mechanism once that lands -- do not build further
features on top of this table without checking PAR-191's status first.

Execution mechanism: a dedicated Cloud Run Job, NOT FastAPI BackgroundTasks.
This choice is load-bearing, not a style preference -- see
docs/PAR-177-async-pdf-implementation-plan.md §2. parity-backend-prod runs
with default Cloud Run CPU throttling (confirmed directly against the live
service config, 2026-08-25: no `run.googleapis.com/cpu-throttling` annotation
present on either the service or its current revision -- CPU is allocated
during request processing only). A ~90-105s CPU-bound render dispatched via
BackgroundTasks would run throttled after the response returns, which could
stall or take far longer than the render itself costs. Cloud Run Jobs do not
have this failure mode -- a Job execution is its own isolated task with full
CPU for its entire lifetime, by design (Jobs have no request/response
distinction to throttle around). Verified empirically, not just from GCP's
documented behaviour: a CPU-bound `sum(range(400_000_000))` loop measured
3.61s locally vs 6.42s as an isolated Cloud Run Job execution on the same
image (parity-backend-prod's current serving digest) -- ~1.8x, consistent
with vCPU clock differences, not the "many minutes or stall" pattern
throttling would produce.

Storage: PDF bytes live in this table's `pdf_bytes` column, not a Storage
bucket. See migration 035's own comment for the full reasoning (Deed's real
PDF is 82KB; prod's Storage has exactly one bucket, "uploads", and a
"parser-requests" bucket referenced elsewhere in the codebase does not exist
there -- a separate, pre-existing bug, not fixed here). This is a real
divergence from PAR-192's literal "bucket + signed URL" scope line, flagged
on the ticket and the PR for review.

"Signed URL" equivalent: rather than a cryptographically pre-signed bucket
link, the content endpoint is a normal authenticated URL
(.../jobs/{job_id}/content) gated by the same _require_snapshot_access check
every other snapshot route already uses. Callers who already hold a Musa
partner key (or an admin-scoped key, or a user session) can fetch it directly
-- no separate signing step, no token to leak, always freshly authorized.
This satisfies PAR-192's actual need (Musa's status/webhook flow gets a
stable URL to hand back) without needing bucket-signing infrastructure this
interim measure doesn't otherwise require.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from ..db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# ~2 weeks per Uzo's suggestion on PAR-192 (scope item 5).
PDF_JOB_RETENTION_DAYS = 14

# NOTE the plural "service-accounts" and the explicit "default" account id.
# Both are load-bearing and were wrong here until PAR-192's live trigger test
# (2026-08-26): "instance/service-account/token" returns a bare 404 from Cloud
# Run's "Metadata Server for Serverless", because the node under instance/ is
# service-accountS/, and each entry under it is keyed by account id ("default"
# or the SA email) with token/email/scopes beneath THAT. Verified empirically
# from inside a real Cloud Run execution: instance/ lists
# "id|region|service-accounts/|zone", and service-accounts/ lists
# "121148713552-compute@developer.gserviceaccount.com/|default/".
_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/token"
)
_CLOUD_RUN_JOB_NAME = os.getenv("PDF_RENDER_CLOUD_RUN_JOB_NAME", "parity-pdf-render")
_CLOUD_RUN_PROJECT = os.getenv("PDF_RENDER_CLOUD_RUN_PROJECT")
_CLOUD_RUN_REGION = os.getenv("PDF_RENDER_CLOUD_RUN_REGION", "us-central1")


# ---------------------------------------------------------------------------
# Job repository
# ---------------------------------------------------------------------------

def create_job(
    deal_id: str,
    variant: str,
    snapshot_id: Optional[str],
    requested_by: Optional[str],
) -> Dict[str, Any]:
    sb = get_supabase()
    row = {
        "job_id": str(uuid.uuid4()),
        "deal_id": deal_id,
        "variant": variant,
        "status": "pending",
        "snapshot_id": snapshot_id,
        "requested_by": requested_by,
    }
    result = sb.table("pds_pdf_jobs").insert(row).execute()
    if not result.data:
        raise RuntimeError("pds_pdf_jobs insert returned no data")
    return result.data[0]


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("pds_pdf_jobs")
        .select("job_id, deal_id, variant, status, snapshot_id, byte_size, "
                "error_message, requested_by, created_at, started_at, completed_at")
        .eq("job_id", job_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_job_bytes(job_id: str) -> Optional[bytes]:
    """Separate from get_job() so status polling never pulls the bytea payload."""
    sb = get_supabase()
    result = (
        sb.table("pds_pdf_jobs")
        .select("pdf_bytes, status")
        .eq("job_id", job_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    row = result.data[0]
    if row.get("status") != "done":
        return None
    raw = row.get("pdf_bytes")
    if raw is None:
        return None
    # supabase-py returns bytea as a hex-prefixed string ("\\x...") over
    # PostgREST; normalise defensively rather than assume the client version's
    # exact encoding.
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, str) and raw.startswith("\\x"):
        return bytes.fromhex(raw[2:])
    raise RuntimeError(f"Unexpected pdf_bytes encoding for job {job_id}: {type(raw)}")


def find_cached_done_job(
    deal_id: str, variant: str, snapshot_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """
    Deterministic-cache short-circuit (PAR-177 plan §1c, mirrors api.py:1039's
    existing export short-circuit idea): a rendered PDF is deterministic for a
    given (deal, variant, snapshot_id). If a done job already exists for this
    exact combination, reuse it instead of re-rendering.
    """
    if snapshot_id is None:
        return None
    sb = get_supabase()
    result = (
        sb.table("pds_pdf_jobs")
        .select("job_id, deal_id, variant, status, snapshot_id, byte_size, "
                "created_at, started_at, completed_at")
        .eq("deal_id", deal_id)
        .eq("variant", variant)
        .eq("snapshot_id", snapshot_id)
        .eq("status", "done")
        .order("completed_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def mark_running(job_id: str) -> None:
    sb = get_supabase()
    sb.table("pds_pdf_jobs").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("job_id", job_id).execute()


def mark_done(job_id: str, pdf_bytes: bytes) -> None:
    sb = get_supabase()
    sb.table("pds_pdf_jobs").update({
        "status": "done",
        # postgrest-py's .update() serializes this dict via httpx's json=
        # (json.dumps under the hood) -- raw bytes are not JSON-serializable
        # and this raised TypeError on every real render (confirmed via a
        # live Cloud Run Job execution, 2026-08-26). PostgREST's actual wire
        # format for a bytea column is a "\x"-prefixed hex string -- the
        # same format get_job_bytes() below already reads back -- so encode
        # to match, rather than pass Python bytes through.
        "pdf_bytes": "\\x" + pdf_bytes.hex(),
        "byte_size": len(pdf_bytes),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("job_id", job_id).execute()


def mark_failed(job_id: str, error_message: str) -> None:
    sb = get_supabase()
    sb.table("pds_pdf_jobs").update({
        "status": "failed",
        "error_message": error_message[:2000],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("job_id", job_id).execute()


def sweep_expired(retention_days: int = PDF_JOB_RETENTION_DAYS) -> int:
    """Delete job rows (and their bytes) older than retention_days. Returns count deleted."""
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    result = (
        sb.table("pds_pdf_jobs")
        .delete()
        .lt("created_at", cutoff)
        .execute()
    )
    return len(result.data or [])


# ---------------------------------------------------------------------------
# Cloud Run Job trigger
# ---------------------------------------------------------------------------

def _fetch_metadata_server_token() -> str:
    """
    Fetch an access token for this instance's own service account via the
    Cloud Run/GCE metadata server. Only works when actually running on
    Cloud Run/GCE -- not locally. No new dependency added (google-auth is
    not otherwise used anywhere in this codebase); this is a plain httpx GET,
    consistent with httpx already being the project's HTTP client.
    """
    resp = httpx.get(
        _METADATA_TOKEN_URL,
        headers={"Metadata-Flavor": "Google"},
        params={"scopes": "https://www.googleapis.com/auth/cloud-platform"},
        timeout=5.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def trigger_render_job(
    job_id: str,
    deal_id: str,
    variant: str,
    *,
    token_fetcher=_fetch_metadata_server_token,
    http_client: Optional[httpx.Client] = None,
) -> None:
    """
    Start a Cloud Run Job execution to render this job. Fire-and-forget: this
    function returns once the execution has been ACCEPTED (Cloud Run Admin
    API v2's `:run` call returns immediately with a long-running-operation
    reference), not once rendering completes. The caller (the POST endpoint)
    should return 202 right after this returns.

    This HTTP call itself is fast (not CPU-bound) and safe to make inline in
    a request handler -- it is the render *inside* the triggered Job that is
    expensive, and that runs in a separate, isolated execution with its own
    full CPU allocation (see module docstring).

    token_fetcher / http_client are injectable for tests -- this function
    must not require a real GCP environment to be unit-testable.
    """
    if not _CLOUD_RUN_PROJECT:
        raise RuntimeError(
            "PDF_RENDER_CLOUD_RUN_PROJECT is not set. This is required deploy-time "
            "config (same class as SUPABASE_URL etc.) and is NOT auto-detected, "
            "deliberately, so that job execution never silently targets the wrong "
            "project."
        )

    token = token_fetcher()
    url = (
        f"https://run.googleapis.com/v2/projects/{_CLOUD_RUN_PROJECT}/locations/"
        f"{_CLOUD_RUN_REGION}/jobs/{_CLOUD_RUN_JOB_NAME}:run"
    )
    body = {
        "overrides": {
            "containerOverrides": [{
                "args": [
                    "-m", "v1.scripts.render_pdf_job",
                    "--job-id", job_id,
                    "--deal-id", deal_id,
                    "--variant", variant,
                ],
            }],
            "taskCount": 1,
        }
    }
    client = http_client or httpx
    resp = client.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=15.0,
    )
    if resp.status_code >= 400:
        logger.error(
            "[PAR-192] Cloud Run Job trigger failed for job_id=%s deal_id=%s: %s %s",
            job_id, deal_id, resp.status_code, resp.text[:500],
        )
        mark_failed(job_id, f"Failed to start render job: HTTP {resp.status_code}")
        return
    logger.info(
        "[PAR-192] Cloud Run Job execution started for job_id=%s deal_id=%s variant=%s",
        job_id, deal_id, variant,
    )


# ---------------------------------------------------------------------------
# Retention sweeper — mirrors ParserRequestSlaSweeper's exact shape
# (musa_parser_request_sla.py), started from main.py's lifespan.
# ---------------------------------------------------------------------------

class PdfJobRetentionSweeper:
    """Daily background loop deleting job rows (and their bytes) older than
    PDF_JOB_RETENTION_DAYS, per PAR-192 scope item 5 (~2 weeks, Uzo's
    suggestion). Started from main.py's lifespan."""

    def __init__(self, poll_interval: int = 86400):
        self.poll_interval = poll_interval
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("[PAR-192] Retention sweeper started (poll_interval=%ds)", self.poll_interval)
        while self._running:
            try:
                deleted = await asyncio.to_thread(sweep_expired)
                if deleted:
                    logger.info("[PAR-192] Retention sweep deleted %d expired pdf job row(s)", deleted)
            except Exception:
                logger.exception("[PAR-192] Retention sweep loop error")
            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
        logger.info("[PAR-192] Retention sweeper stopped")


pdf_job_retention_sweeper = PdfJobRetentionSweeper()
