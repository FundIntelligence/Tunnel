"""
24-hour SLA sweep for Musa parser_requests rows (PAR-62).

Design (Uzoma's proposal from the call): when a Musa document fails
because Parity doesn't recognise its format, Musa isn't told immediately —
engineers get a 24h window to ship a parser for the new format, and this
sweep silently retries ingestion against the persisted sample
(parser_requests.storage_path, PAR-34) each time it runs. musa_sessions
stays "processing" during that window. Only once the window elapses
without a successful retry does the request get force-closed as failed
and the webhook Musa actually depends on gets sent — so it's deferred,
never dropped: PAR-60's no-silent-failure guarantee still holds for this
failure class, just on a 24h delay instead of immediately.

Runs hourly, started as a background asyncio task from main.py's lifespan
(mirrors the MusaWorker polling-loop pattern in v1/musa/worker.py).
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..db.supabase_client import get_supabase
from ..db.supabase_repositories import (
    AnalysisRunsRepo,
    DealsRepo,
    DocumentsRepo,
    RawTxRepo,
)
from ..ingestion.service import IngestionService
from .musa_file_processor import _run_export, _send_webhook

logger = logging.getLogger(__name__)

_SLA_WINDOW = timedelta(hours=24)
_SERVICE_UUID = "00000000-0000-0000-0000-000000000001"


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _base_url() -> str:
    return os.getenv("API_BASE_URL", "https://parity-ingestion.onrender.com")


def _get_musa_session(supabase, session_id: str) -> Optional[Dict[str, Any]]:
    try:
        result = (
            supabase.table("musa_sessions")
            .select("*")
            .eq("session_id", session_id)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception:
        logger.exception("[MUSA-SLA] Failed to load musa_sessions row=%s", session_id)
        return None


def _attempt_retry(supabase, row: Dict[str, Any]) -> bool:
    """
    Re-download the persisted sample and re-run ingestion against the
    original deal. Returns True on success (caller resolves the request
    and completes the session), False to leave it pending for next sweep.
    """
    deal_id = row.get("deal_id")
    storage_path = row.get("storage_path")
    if not deal_id or not storage_path:
        return False  # nothing to retry against — leave pending

    deal = DealsRepo().get_deal(deal_id)
    if not deal:
        return False

    try:
        file_bytes = supabase.storage.from_("parser-requests").download(storage_path)
    except Exception:
        logger.warning(
            "[MUSA-SLA] Could not download sample %s for retry", storage_path
        )
        return False

    file_name = Path(storage_path).name
    file_type = Path(storage_path).suffix.lstrip(".") or "pdf"
    document_id = str(uuid.uuid4())

    docs_repo = DocumentsRepo()
    docs_repo.create_document({
        "id": document_id,
        "deal_id": deal_id,
        "storage_url": f"inline://{file_name}",
        "file_type": file_type,
        "status": "processing",
        "currency_detected": None,
        "currency_mismatch": False,
        "created_by": _SERVICE_UUID,
    })

    ingestion_svc = IngestionService(
        documents_repo=docs_repo,
        raw_tx_repo=RawTxRepo(),
        analysis_repo=AnalysisRunsRepo(),
    )

    try:
        ingestion_svc.process_document_background(
            document_id=document_id,
            deal_id=deal_id,
            created_by=_SERVICE_UUID,
            file_bytes=file_bytes,
            file_name=file_name,
            file_type=file_type,
            deal_currency=deal["currency"],
        )
        _run_export(deal_id, _SERVICE_UUID)
    except Exception as exc:
        logger.info(
            "[MUSA-SLA] Retry still failing request=%s deal=%s: %s",
            row.get("id"), deal_id, exc,
        )
        return False

    return True


async def _resolve_success(supabase, row: Dict[str, Any]) -> None:
    session_id = row.get("session_id")
    deal_id = row.get("deal_id")
    now = datetime.now(timezone.utc).isoformat()

    supabase.table("parser_requests").update(
        {"status": "resolved", "updated_at": now}
    ).eq("id", row["id"]).execute()

    if not session_id:
        return

    session = _get_musa_session(supabase, session_id)

    supabase.table("musa_sessions").update(
        {"status": "complete", "completed_at": now}
    ).eq("session_id", session_id).execute()

    base_url = _base_url()
    await _send_webhook(
        session_id=session_id,
        venture_name=(session or {}).get("venture_name", ""),
        venture_country=(session or {}).get("venture_country", row.get("market", "")),
        status="complete",
        status_url=f"{base_url}/api/musa/sessions/{session_id}/status",
        pdf_url=f"{base_url}/v1/deals/{deal_id}/snapshot/pdf",
        created_at=(session or {}).get("created_at", now),
        completed_at=now,
    )
    logger.info(
        "[MUSA-SLA] Retry succeeded — session=%s resolved via SLA sweep", session_id
    )


async def _force_close_expired(supabase, row: Dict[str, Any]) -> None:
    session_id = row.get("session_id")
    now = datetime.now(timezone.utc).isoformat()
    error_message = (
        "No parser available for this document format within the 24h SLA window"
    )

    supabase.table("parser_requests").update(
        {"status": "expired", "updated_at": now}
    ).eq("id", row["id"]).execute()

    if not session_id:
        return

    session = _get_musa_session(supabase, session_id)

    supabase.table("musa_sessions").update(
        {"status": "failed", "completed_at": now, "error_message": error_message}
    ).eq("session_id", session_id).execute()

    base_url = _base_url()
    await _send_webhook(
        session_id=session_id,
        venture_name=(session or {}).get("venture_name", ""),
        venture_country=(session or {}).get("venture_country", row.get("market", "")),
        status="failed",
        status_url=f"{base_url}/api/musa/sessions/{session_id}/status",
        error_message=error_message,
        created_at=(session or {}).get("created_at", now),
        completed_at=now,
    )
    logger.warning(
        "[MUSA-SLA] request=%s session=%s force-closed — SLA elapsed, webhook sent",
        row.get("id"), session_id,
    )


async def sweep_parser_request_sla() -> None:
    """
    Hourly entry point. Scans partner="musa" parser_requests still
    "pending": retries silently within the 24h window, force-closes (with
    webhook) once the window elapses.
    """
    supabase = get_supabase()
    try:
        result = (
            supabase.table("parser_requests")
            .select("*")
            .eq("partner", "musa")
            .eq("status", "pending")
            .execute()
        )
    except Exception:
        logger.exception("[MUSA-SLA] Failed to query pending parser_requests")
        return

    rows = result.data or []
    if not rows:
        return

    now = datetime.now(timezone.utc)
    logger.info("[MUSA-SLA] Sweeping %d pending musa parser_request(s)", len(rows))

    for row in rows:
        requested_at = row.get("requested_at")
        if not requested_at:
            continue

        try:
            age = now - _parse_ts(requested_at)

            if age >= _SLA_WINDOW:
                await _force_close_expired(supabase, row)
                continue

            if await asyncio.to_thread(_attempt_retry, supabase, row):
                await _resolve_success(supabase, row)
        except Exception:
            logger.exception(
                "[MUSA-SLA] Unexpected error sweeping parser_request=%s", row.get("id")
            )


class ParserRequestSlaSweeper:
    """Hourly background loop, started from main.py's lifespan."""

    def __init__(self, poll_interval: int = 3600):
        self.poll_interval = poll_interval
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("[MUSA-SLA] Started (poll_interval=%ds)", self.poll_interval)
        while self._running:
            try:
                await sweep_parser_request_sla()
            except Exception:
                logger.exception("[MUSA-SLA] Sweep loop error")
            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
        logger.info("[MUSA-SLA] Stopped")


# Global singleton — imported by main.py
parser_request_sla_sweeper = ParserRequestSlaSweeper()
