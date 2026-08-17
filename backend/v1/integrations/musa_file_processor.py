"""
Musa Ventures file processing pipeline.

Downloads files from signed URLs, ingests through Parity pipeline,
runs the deterministic export to build a snapshot, then sends a webhook.

Design notes
------------
* Async throughout to support httpx.AsyncClient for HTTP I/O.
* Blocking sync DB/ingestion calls are invoked directly — acceptable for
  background tasks (not in the request hot-path). TODO: wrap in
  asyncio.to_thread() before production to avoid event-loop stalls on
  large files.
* Webhook failures are logged and never retried; Musa polls via status_url.
* No floats: money stays in integer cents throughout the pipeline.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx

from ..db.supabase_client import get_supabase
from ..db.supabase_repositories import (
    AnalysisRunsRepo,
    DealsRepo,
    DocumentsRepo,
    EntitiesRepo,
    OverridesRepo,
    RawTxRepo,
    SnapshotsRepo,
    TransferLinksRepo,
    TxnEntityMapRepo,
)
from ..ingestion.service import IngestionService
from .currency_utils import country_to_currency

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".pdf"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_extension(url: str, file_type_hint: Optional[str]) -> str:
    """
    Derive a safe file extension from the URL (before any query string),
    then fall back to file_type_hint, then default to .pdf.
    """
    path = url.split("?")[0]
    ext = Path(path).suffix.lower()
    if ext in _ALLOWED_EXTENSIONS:
        return ext
    hint_map = {
        "bank_statement": ".pdf",
        "mpesa": ".csv",
        "audited_financials": ".pdf",
        "xlsx": ".xlsx",
        "csv": ".csv",
    }
    if file_type_hint:
        return hint_map.get(file_type_hint.lower(), ".pdf")
    return ".pdf"


async def _download_file(url: str, timeout: int = 300) -> bytes:
    """Download a file from a signed URL and return raw bytes."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def _run_export(deal_id: str, created_by: str) -> dict:
    """
    Run the Parity deterministic pipeline and persist a snapshot.

    Mirrors the core of POST /v1/deals/{deal_id}/export without the HTTP
    layer.  Raises ValueError if no transactions exist (ingestion failed).
    """
    from ..core.pipeline import run_pipeline
    from ..core.snapshot_engine import build_pds_payload, export_snapshot

    deals_repo = DealsRepo()
    raw_repo = RawTxRepo()
    overrides_repo = OverridesRepo()
    txn_map_repo = TxnEntityMapRepo()
    links_repo = TransferLinksRepo()
    entities_repo = EntitiesRepo()
    runs_repo = AnalysisRunsRepo()
    snapshots_repo = SnapshotsRepo()

    deal = deals_repo.get_deal(deal_id)
    if not deal:
        raise ValueError(f"Deal {deal_id} not found")

    raw = list(raw_repo.list_by_deal(deal_id))
    if not raw:
        raise ValueError(
            f"No transactions for deal {deal_id} — ingestion may have failed"
        )

    overrides = list(overrides_repo.list_overrides(deal_id))

    run, links, entities, txn_map = run_pipeline(
        deal_id=deal_id,
        raw_transactions=raw,
        overrides=overrides,
        accrual={
            "accrual_revenue_cents": deal.get("accrual_revenue_cents"),
            "accrual_period_start": deal.get("accrual_period_start"),
            "accrual_period_end": deal.get("accrual_period_end"),
        },
    )

    # Remap text txn_ids → UUIDs (matches api.py export logic)
    txn_id_to_uuid = {tx["txn_id"]: tx["id"] for tx in raw if "id" in tx}
    for rec in txn_map:
        if rec["txn_id"] in txn_id_to_uuid:
            rec["txn_id"] = txn_id_to_uuid[rec["txn_id"]]
    for lnk in links:
        lnk.pop("id", None) if lnk.get("id") is None else None

    txn_map_repo.delete_eq("deal_id", deal_id)
    links_repo.delete_eq("deal_id", deal_id)
    entities_repo.delete_eq("deal_id", deal_id)

    run_for_db = {k: v for k, v in run.items() if k != "bank_operational_inflow_cents"}
    runs_repo.insert_run(run_for_db)
    links_repo.insert_batch(links)
    entities_repo.upsert_entities(entities)
    txn_map_repo.upsert_mappings(txn_map)

    payload = build_pds_payload(
        schema_version=run["schema_version"],
        config_version=run["config_version"],
        deal_id=deal_id,
        currency=deal["currency"],
        raw_transactions=raw,
        transfer_links=links,
        entities=entities,
        txn_entity_map=txn_map,
        metrics={
            "coverage_bp": run["coverage_pct_bp"],
            "missing_month_count": run["missing_month_count"],
            "missing_month_penalty_bp": run["missing_month_penalty_bp"],
            "reconciliation_status": run["reconciliation_status"],
            "reconciliation_bp": run["reconciliation_pct_bp"],
        },
        confidence={
            "final_confidence_bp": run["final_confidence_bp"],
            "tier": run["tier"],
            "tier_capped": run["tier_capped"],
            "override_penalty_bp": run["override_penalty_bp"],
        },
        overrides_applied=overrides,
        audited_financials=None,
    )

    return export_snapshot(
        snapshot_repo=snapshots_repo,
        deal_id=deal_id,
        analysis_run_id=run["id"],
        payload=payload,
        created_by=created_by,
    )


async def _send_webhook(
    session_id: str,
    venture_name: str,
    venture_country: str,
    status: str,
    status_url: str,
    pdf_url: Optional[str] = None,
    error_message: Optional[str] = None,
    created_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> None:
    """
    POST the unified SessionResponse payload to Musa's webhook endpoint.

    Payload shape is IDENTICAL to GET /status response so Musa can use
    the same deserialisation logic for both polling and push.
    """
    webhook_url = os.getenv("MUSA_WEBHOOK_URL")
    webhook_token = os.getenv("MUSA_WEBHOOK_AUTH_TOKEN")

    if not webhook_url or not webhook_token:
        logger.warning(
            "[MUSA] Webhook env vars not set — skipping delivery (session=%s)", session_id
        )
        return

    payload = {
        "session_id": session_id,
        "venture_name": venture_name,
        "venture_country": venture_country,
        "status": status,
        "status_url": status_url,
        "pdf_url": pdf_url,
        "error_message": error_message,
        "created_at": created_at,
        "completed_at": completed_at,
    }
    headers = {
        "x-api-key": webhook_token,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(webhook_url, json=payload, headers=headers)
        if resp.status_code == 200:
            logger.info("[MUSA] Webhook delivered session=%s", session_id)
        else:
            logger.error(
                "[MUSA] Webhook non-200 session=%s status=%d body=%s",
                session_id, resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        # Never raise — Musa has status polling as fallback
        logger.error("[MUSA] Webhook exception session=%s: %s", session_id, exc)


# ---------------------------------------------------------------------------
# Main background task
# ---------------------------------------------------------------------------

async def process_musa_session(
    session_id: str,
    deal_id: str,
    venture_name: str,
    venture_country: str,
    documents: List[dict],
    status_url: str,
    created_at: str,
) -> None:
    """
    Background task: download files → ingest → export/snapshot → webhook.

    Args:
        session_id:      musa_sessions.session_id (PK)
        deal_id:         linked pds_deals.id
        venture_name:    company name (for webhook payload)
        venture_country: country name (used to derive currency and for webhook)
        documents:       list of dicts with 'url', 'file_type', 'date_from', 'date_to'
        status_url:      full URL for Musa's status polling fallback
        created_at:      ISO timestamp of session creation
    """
    logger.info(
        "[MUSA] Processing started session=%s deal=%s docs=%d",
        session_id, deal_id, len(documents),
    )

    supabase = get_supabase()
    try:
        deal_currency = country_to_currency(venture_country)
    except ValueError as exc:
        logger.error(
            "[MUSA] Cannot resolve currency for country=%r session=%s: %s",
            venture_country, session_id, exc,
        )
        raise RuntimeError(str(exc)) from exc
    service_uuid = "00000000-0000-0000-0000-000000000001"  # Musa system user

    docs_repo = DocumentsRepo()
    ingestion_svc = IngestionService(
        documents_repo=docs_repo,
        raw_tx_repo=RawTxRepo(),
        analysis_repo=AnalysisRunsRepo(),
    )

    try:
        for i, doc in enumerate(documents):
            url = doc.get("url", "") if isinstance(doc, dict) else getattr(doc, "url", "")
            file_type_hint = (
                doc.get("file_type") if isinstance(doc, dict) else getattr(doc, "file_type", None)
            )

            logger.info(
                "[MUSA] Downloading doc %d/%d session=%s url=%.60s",
                i + 1, len(documents), session_id, url,
            )
            file_bytes = await _download_file(url)

            ext = _infer_extension(url, file_type_hint)
            hint_label = file_type_hint or "doc"
            original_name = Path(url.split("?")[0]).name
            file_name = original_name if original_name and len(original_name) > 4 else f"musa_{hint_label}_{i + 1}{ext}"
            file_type = ext.lstrip(".")

            # Create pds_documents row before calling process_document_background
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
                "[MUSA] Ingesting doc %d/%d document_id=%s session=%s",
                i + 1, len(documents), document_id, session_id,
            )
            # Run synchronously in the async context — blocks coroutine but
            # acceptable for background tasks.  Use asyncio.to_thread() here
            # once we validate the full pipeline end-to-end.
            await asyncio.to_thread(
                ingestion_svc.process_document_background,
                document_id=document_id,
                deal_id=deal_id,
                created_by=service_uuid,
                file_bytes=file_bytes,
                file_name=file_name,
                file_type=file_type,
                deal_currency=deal_currency,
            )

        # Run deterministic pipeline + build snapshot
        logger.info("[MUSA] Running export pipeline deal=%s session=%s", deal_id, session_id)
        await asyncio.to_thread(_run_export, deal_id, service_uuid)

        # Mark session complete
        completed_at = datetime.now(timezone.utc).isoformat()
        supabase.table("musa_sessions").update(
            {"status": "complete", "completed_at": completed_at}
        ).eq("session_id", session_id).execute()

        base_url = os.getenv("API_BASE_URL", "https://parity-ingestion.onrender.com")
        pdf_url = f"{base_url}/v1/deals/{deal_id}/snapshot/pdf"

        logger.info("[MUSA] Session complete session=%s pdf_url=%s", session_id, pdf_url)
        await _send_webhook(
            session_id=session_id,
            venture_name=venture_name,
            venture_country=venture_country,
            status="complete",
            status_url=status_url,
            pdf_url=pdf_url,
            created_at=created_at,
            completed_at=completed_at,
        )

    except Exception as exc:
        logger.exception("[MUSA] Session failed session=%s: %s", session_id, exc)
        completed_at = datetime.now(timezone.utc).isoformat()

        # Map common errors to friendly messages
        error_str = str(exc).lower()
        if "name or service not known" in error_str or "failed to resolve" in error_str:
            error_message = "Failed to download document: URL unreachable or invalid"
        elif "timeout" in error_str or "timed out" in error_str:
            error_message = "Failed to download document: Request timed out"
        elif "http" in error_str and ("40" in error_str or "50" in error_str):
            error_message = f"Failed to download document: Server returned error ({exc})"
        else:
            # For unexpected errors, still include the original for debugging
            error_message = f"Processing failed: {exc}"

        if "no transactions" in error_str or "unsupported" in error_str:
            try:
                _doc_url = documents[0].get("url") if documents else None
                get_supabase().table("parser_requests").insert({
                    "partner": "musa",
                    "market": venture_country,
                    "document_url": _doc_url,
                    "session_id": str(session_id),
                    "error_message": str(exc),
                    "status": "pending",
                }).execute()
            except Exception:
                pass  # never let parser_requests insert block the main flow

        try:
            supabase.table("musa_sessions").update(
                {
                    "status": "failed",
                    "completed_at": completed_at,
                    "error_message": error_message,
                }
            ).eq("session_id", session_id).execute()
        except Exception:
            logger.exception("[MUSA] Failed to persist error state session=%s", session_id)

        await _send_webhook(
            session_id=session_id,
            venture_name=venture_name,
            venture_country=venture_country,
            status="failed",
            status_url=status_url,
            error_message=error_message,
            created_at=created_at,
            completed_at=completed_at,
        )
