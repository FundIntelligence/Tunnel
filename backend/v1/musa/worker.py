"""
Background polling worker for pds_musa_sessions.

Polls every `poll_interval` seconds for pending jobs, processes each file
through the existing Parity ingestion pipeline, then POSTs results to the
session's webhook_url.

Design notes
------------
* Runs as an asyncio background task started at FastAPI lifespan startup.
* Uses the existing IngestionService and _run_export from musa_file_processor
  so the full Parity pipeline (parse → normalise → snapshot) is reused.
* If no deal_id is supplied, a deal is created from metadata.venture_name
  (defaulting to "Musa Session <session_id>") with currency KES.
* Max 3 retries per session; failed sessions post error payload to webhook.
* Webhook failures are logged and never retried — caller can poll via GET.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..integrations.musa_deploy_config import API_BASE_URL

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".pdf"}
_DEFAULT_CURRENCY = "KES"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_extension(url: str) -> str:
    path = url.split("?")[0]
    ext = Path(path).suffix.lower()
    return ext if ext in _ALLOWED_EXTENSIONS else ".pdf"


async def _download_file(url: str, timeout: int = 300) -> bytes:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def _post_webhook(webhook_url: str, payload: Dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(webhook_url, json=payload)
        if resp.status_code == 200:
            logger.info("[MusaWorker] Webhook delivered to %s", webhook_url)
        else:
            logger.error(
                "[MusaWorker] Webhook non-200: status=%d body=%.200s",
                resp.status_code, resp.text,
            )
    except Exception as exc:
        logger.error("[MusaWorker] Webhook exception: %s", exc)


# ---------------------------------------------------------------------------
# Session processing
# ---------------------------------------------------------------------------

async def _process_session(session: Dict[str, Any]) -> None:
    from ..db.supabase_client import get_supabase
    from ..db.supabase_repositories import (
        AnalysisRunsRepo, DealsRepo, DocumentsRepo,
        RawTxRepo,
    )
    from ..ingestion.service import IngestionService
    from ..integrations.musa_file_processor import _run_export  # reuse existing export

    session_id = session["session_id"]
    file_urls: List[str] = session.get("file_urls") or []
    webhook_url: Optional[str] = session.get("webhook_url")
    metadata: dict = session.get("metadata") or {}

    supabase = get_supabase()

    # Mark as processing
    supabase.table("pds_musa_sessions").update({
        "status": "processing",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("session_id", session_id).execute()

    logger.info("[MusaWorker] Processing session=%s files=%d", session_id, len(file_urls))

    try:
        # Resolve or create deal
        deal_id = session.get("deal_id")
        if not deal_id:
            venture_name = metadata.get("venture_name", f"Musa Session {session_id}")
            currency = metadata.get("currency", _DEFAULT_CURRENCY)
            service_uuid = "00000000-0000-0000-0000-000000000001"
            deal = DealsRepo().create_deal({
                "id": str(uuid.uuid4()),
                "currency": currency,
                "name": venture_name,
                "created_by": service_uuid,
            })
            deal_id = deal["id"]
            # Persist deal_id on session so GET /status can surface it
            supabase.table("pds_musa_sessions").update(
                {"deal_id": deal_id}
            ).eq("session_id", session_id).execute()

        service_uuid = "00000000-0000-0000-0000-000000000001"
        docs_repo = DocumentsRepo()
        ingestion_svc = IngestionService(
            documents_repo=docs_repo,
            raw_tx_repo=RawTxRepo(),
            analysis_repo=AnalysisRunsRepo(),
        )

        for i, url in enumerate(file_urls):
            logger.info(
                "[MusaWorker] Downloading file %d/%d session=%s url=%.80s",
                i + 1, len(file_urls), session_id, url,
            )
            file_bytes = await _download_file(url)
            ext = _infer_extension(url)
            file_type = ext.lstrip(".")
            file_name = f"musa_{i + 1}{ext}"

            document_id = str(uuid.uuid4())
            docs_repo.create_document({
                "id": document_id,
                "deal_id": deal_id,
                "storage_url": f"inline://{file_name}",
                "file_type": file_type,
                "status": "processing",
                "currency_detected": None,
                "currency_mismatch": False,
                "created_by": service_uuid,
            })

            logger.info(
                "[MusaWorker] Ingesting document_id=%s session=%s",
                document_id, session_id,
            )
            await asyncio.to_thread(
                ingestion_svc.process_document_background,
                document_id=document_id,
                deal_id=deal_id,
                created_by=service_uuid,
                file_bytes=file_bytes,
                file_name=file_name,
                file_type=file_type,
                deal_currency=metadata.get("currency", _DEFAULT_CURRENCY),
            )

        # Build snapshot via existing export pipeline
        logger.info("[MusaWorker] Running export pipeline deal=%s session=%s", deal_id, session_id)
        await asyncio.to_thread(_run_export, deal_id, service_uuid)

        completed_at = datetime.now(timezone.utc).isoformat()
        supabase.table("pds_musa_sessions").update({
            "status": "completed",
            "completed_at": completed_at,
        }).eq("session_id", session_id).execute()

        logger.info("[MusaWorker] Session completed session=%s", session_id)

        if webhook_url:
            base_url = API_BASE_URL
            await _post_webhook(webhook_url, {
                "session_id": session_id,
                "status": "completed",
                "deal_id": deal_id,
                "pdf_url": f"{base_url}/v1/deals/{deal_id}/snapshot/pdf",
                "completed_at": completed_at,
            })

    except Exception as exc:
        logger.exception("[MusaWorker] Session failed session=%s: %s", session_id, exc)

        error_str = str(exc).lower()
        if "name or service not known" in error_str or "failed to resolve" in error_str:
            error_message = "Failed to download document: URL unreachable or invalid"
        elif "timeout" in error_str or "timed out" in error_str:
            error_message = "Failed to download document: request timed out"
        elif "http" in error_str and ("40" in error_str or "50" in error_str):
            error_message = f"Failed to download document: server error ({exc})"
        else:
            error_message = f"Processing failed: {exc}"

        completed_at = datetime.now(timezone.utc).isoformat()
        try:
            supabase.table("pds_musa_sessions").update({
                "status": "failed",
                "completed_at": completed_at,
                "error_message": error_message,
                "retry_count": session["retry_count"] + 1,
            }).eq("session_id", session_id).execute()
        except Exception:
            logger.exception("[MusaWorker] Failed to persist error state session=%s", session_id)

        if webhook_url:
            await _post_webhook(webhook_url, {
                "session_id": session_id,
                "status": "failed",
                "error_message": error_message,
                "completed_at": completed_at,
            })


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

class MusaWorker:
    def __init__(self, poll_interval: int = 10):
        self.poll_interval = poll_interval
        self.is_running = False

    async def start(self) -> None:
        self.is_running = True
        logger.info("[MusaWorker] Started (poll_interval=%ds)", self.poll_interval)
        while self.is_running:
            try:
                await self._poll()
            except Exception as exc:
                logger.error("[MusaWorker] Poll error: %s", exc, exc_info=True)
            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self.is_running = False
        logger.info("[MusaWorker] Stopped")

    async def _poll(self) -> None:
        from ..db.supabase_client import get_supabase

        supabase = get_supabase()
        result = (
            supabase.table("pds_musa_sessions")
            .select("*")
            .eq("status", "pending")
            .lt("retry_count", _MAX_RETRIES)
            .order("created_at")
            .limit(5)
            .execute()
        )
        sessions = result.data or []
        if not sessions:
            return

        logger.info("[MusaWorker] Found %d pending session(s)", len(sessions))
        for session in sessions:
            try:
                await _process_session(session)
            except Exception as exc:
                logger.error(
                    "[MusaWorker] Unexpected error for session %s: %s",
                    session.get("session_id"), exc,
                )


# Global singleton — imported by main.py
musa_worker = MusaWorker(poll_interval=10)
