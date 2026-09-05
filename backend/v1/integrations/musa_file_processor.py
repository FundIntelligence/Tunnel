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
import re
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
        "Authorization": f"Bearer {webhook_token}",
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


def _persist_raw_document(
    session_id: str,
    file_bytes: Optional[bytes],
    file_name: Optional[str],
) -> Optional[str]:
    """
    Upload a raw Musa document to the `parser-requests` Storage bucket
    (PAR-34 / PAR-248) immediately after download, before any parse attempt.
    This ensures the file survives past the signed-URL expiry regardless of
    whether ingestion succeeds or fails, and gives the SLA sweep (PAR-62) a
    reliable file to retry against.

    Best-effort: a Storage hiccup must not affect musa_sessions state or
    the webhook Musa depends on, so failures are logged and swallowed.
    """
    if not file_bytes or not file_name:
        return None
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file_name)
    object_path = f"musa/{session_id}/{safe_name}"
    try:
        get_supabase().storage.from_("parser-requests").upload(
            object_path,
            file_bytes,
            {"upsert": "true"},
        )
        return object_path
    except Exception:
        logger.exception(
            "[MUSA] Failed to persist raw document to storage session=%s", session_id
        )
        return None


async def _record_unrecognized_document(
    session_id: str,
    deal_id: str,
    venture_country: str,
    document_url: Optional[str],
    error_message: str,
    storage_path: Optional[str] = None,
) -> None:
    """
    Record one document's unrecognized-format failure: log a parser_requests
    row deferred to the 24h SLA sweep (PAR-62) and notify engineers. The
    raw file must already be persisted via _persist_raw_document() before
    this is called — storage_path is passed in, not re-computed here.

    Called once per failing document within a batch — PAR-61: a batch can
    contain several unrecognized files alongside recognizable ones, each
    tracked and retried independently rather than one bad file failing the
    whole batch.
    """
    try:
        get_supabase().table("parser_requests").insert({
            "partner": "musa",
            "market": venture_country,
            "document_url": document_url,
            "session_id": str(session_id),
            "deal_id": deal_id,
            "error_message": error_message,
            "status": "pending",
            "storage_path": storage_path,
        }).execute()
    except Exception:
        # Logged, not swallowed — this previously failed silently with no
        # way to ever notice from the admin dashboard.
        logger.exception(
            "[MUSA] Failed to insert parser_requests row session=%s", session_id
        )
    await _notify_parser_request(
        session_id=session_id,
        deal_id=deal_id,
        venture_country=venture_country,
        document_url=document_url,
        error_message=error_message,
    )


async def _notify_parser_request(
    session_id: str,
    deal_id: str,
    venture_country: str,
    document_url: Optional[str],
    error_message: str,
) -> None:
    """
    Email the team that a Musa file failed with an unsupported/unparseable
    format, via the existing Next.js /api/request-parser endpoint (which
    owns the Resend integration — the Python backend has no email creds of
    its own). Tags the request partner="musa" so the route skips its
    pds_parser_requests insert (this path already wrote to parser_requests
    directly, just above) and the email is the only thing left to do here.

    Best-effort only: this must never affect musa_sessions state or the
    webhook Musa actually depends on.
    """
    frontend_url = os.getenv("PARITY_FRONTEND_URL", "https://parity-sme-staging.vercel.app")
    notify_url = f"{frontend_url.rstrip('/')}/api/request-parser"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                notify_url,
                json={
                    "partner": "musa",
                    "bank_name": "Unknown — auto-detected ingestion failure",
                    "country": venture_country,
                    "notes": error_message,
                    "deal_id": deal_id,
                    "original_filename": document_url,
                },
            )
        if resp.status_code != 200:
            logger.error(
                "[MUSA] Parser-request notify non-200 session=%s status=%d body=%s",
                session_id, resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        logger.error("[MUSA] Parser-request notify exception session=%s: %s", session_id, exc)


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

    try:
        supabase = get_supabase()
        deal_currency = country_to_currency(venture_country)
        service_uuid = "00000000-0000-0000-0000-000000000001"  # Musa system user

        docs_repo = DocumentsRepo()
        ingestion_svc = IngestionService(
            documents_repo=docs_repo,
            raw_tx_repo=RawTxRepo(),
            analysis_repo=AnalysisRunsRepo(),
        )

        # PAR-61: a batch can mix recognizable and unrecognizable files —
        # one bad document must not fail documents that would otherwise
        # succeed. Each document is tried independently; failures are
        # classified and recorded per-document instead of aborting the
        # loop.
        succeeded_count = 0
        unrecognized_count = 0
        other_failure: Optional[Exception] = None  # first non-format failure

        for i, doc in enumerate(documents):
            url = doc.get("url", "") if isinstance(doc, dict) else getattr(doc, "url", "")
            file_type_hint = (
                doc.get("file_type") if isinstance(doc, dict) else getattr(doc, "file_type", None)
            )

            logger.info(
                "[MUSA] Downloading doc %d/%d session=%s url=%.60s",
                i + 1, len(documents), session_id, url,
            )

            file_bytes: Optional[bytes] = None
            file_name: Optional[str] = None
            raw_storage_path: Optional[str] = None
            try:
                file_bytes = await _download_file(url)

                ext = _infer_extension(url, file_type_hint)
                hint_label = file_type_hint or "doc"
                original_name = Path(url.split("?")[0]).name
                file_name = original_name if original_name and len(original_name) > 4 else f"musa_{hint_label}_{i + 1}{ext}"
                file_type = ext.lstrip(".")

                # PAR-248: persist the raw file to our own storage immediately
                # after download, before attempting to parse. This guarantees
                # storage_path is populated on any parser_requests row we
                # create, even if parsing fails — the SLA retry sweep (PAR-62)
                # depends on storage_path to re-download and retry the file.
                raw_storage_path = _persist_raw_document(session_id, file_bytes, file_name)

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
                succeeded_count += 1

            except Exception as doc_exc:
                logger.warning(
                    "[MUSA] doc %d/%d failed session=%s url=%.60s: %s",
                    i + 1, len(documents), session_id, url, doc_exc,
                )
                doc_error_str = str(doc_exc).lower()
                if "no transactions" in doc_error_str or "unsupported" in doc_error_str:
                    unrecognized_count += 1
                    await _record_unrecognized_document(
                        session_id=session_id,
                        deal_id=deal_id,
                        venture_country=venture_country,
                        document_url=url,
                        error_message=str(doc_exc),
                        storage_path=raw_storage_path,
                    )
                elif other_failure is None:
                    other_failure = doc_exc
                continue

        if succeeded_count == 0:
            if other_failure is not None:
                # A genuine (non-format) error and nothing else in the
                # batch worked — fall through to the generic failure
                # handling below exactly as before PAR-61.
                raise other_failure
            # Every document in the batch failed on format recognition,
            # each already recorded above (parser_requests + sample +
            # notify). Defer the whole session to the SLA sweep exactly
            # like the single-document case (PAR-62) — no immediate
            # failure webhook.
            logger.info(
                "[MUSA] session=%s all %d document(s) deferred to 24h SLA window",
                session_id, len(documents),
            )
            return

        # At least one document ingested successfully. PAR-61: a batch
        # with some unrecognized-format files must not fail entirely —
        # export + complete on whatever raw transactions did land, and
        # surface the partial-failure count for visibility.
        logger.info("[MUSA] Running export pipeline deal=%s session=%s", deal_id, session_id)
        await asyncio.to_thread(_run_export, deal_id, service_uuid)

        completed_at = datetime.now(timezone.utc).isoformat()
        partial_note: Optional[str] = None
        failed_total = unrecognized_count + (1 if other_failure else 0)
        if failed_total:
            partial_note = (
                f"{succeeded_count} of {len(documents)} document(s) processed "
                f"successfully; {failed_total} could not be processed."
            )

        supabase.table("musa_sessions").update(
            {"status": "complete", "completed_at": completed_at, "error_message": partial_note}
        ).eq("session_id", session_id).execute()

        base_url = os.getenv("API_BASE_URL", "https://parity-ingestion.onrender.com")
        pdf_url = f"{base_url}/v1/deals/{deal_id}/snapshot/pdf"

        logger.info(
            "[MUSA] Session complete session=%s pdf_url=%s partial=%s",
            session_id, pdf_url, bool(partial_note),
        )
        await _send_webhook(
            session_id=session_id,
            venture_name=venture_name,
            venture_country=venture_country,
            status="complete",
            status_url=status_url,
            pdf_url=pdf_url,
            error_message=partial_note,
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

        # Unrecognized-format handling (PAR-62's 24h SLA deferral) happens
        # per-document inside the loop above via _record_unrecognized_document
        # — every document that fails that way is already recorded there,
        # regardless of whether it ends up here. This block only ever runs
        # for a genuine setup-phase failure (before the loop) or a non-format
        # per-document failure re-raised via `other_failure` when nothing in
        # the batch succeeded (PAR-61) — both are real errors Musa needs to
        # hear about immediately, not candidates for the SLA window.
        try:
            get_supabase().table("musa_sessions").update(
                {
                    "status": "failed",
                    "completed_at": completed_at,
                    "error_message": error_message,
                }
            ).eq("session_id", session_id).execute()
        except Exception:
            # DB write failing must not stop the webhook below — Musa's
            # notification is the mechanism of record, status update is
            # best-effort.
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
