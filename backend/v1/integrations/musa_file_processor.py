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
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

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
from .musa_deploy_config import API_BASE_URL, PARITY_FRONTEND_URL

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

    # PAR-238: same fix as api.py's export() — read accrual figures from the
    # confirmed pds_audited_financials record, not the disconnected
    # deal.accrual_* fields (set once at deal-creation, never updated when
    # financials are confirmed afterward). This MUSA-triggered path is a
    # second, independent call site for run_pipeline() with the exact same
    # bug, so it needs the identical fix — leaving it unfixed would mean
    # MUSA-driven exports keep hitting NOT_RUN after the primary export path
    # is fixed, which defeats the point of moving to a single source of truth.
    from ..db.supabase_repositories import AuditedFinancialsRepo
    confirmed_af = AuditedFinancialsRepo().get_latest_confirmed(deal_id)
    run, links, entities, txn_map = run_pipeline(
        deal_id=deal_id,
        raw_transactions=raw,
        overrides=overrides,
        accrual={
            "accrual_revenue_cents": confirmed_af.get("turnover_cents") if confirmed_af else None,
            "accrual_period_start": confirmed_af.get("financial_year_start") if confirmed_af else None,
            "accrual_period_end": confirmed_af.get("financial_year_end") if confirmed_af else None,
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
    is_retry: bool = False,
    resend_count: int = 0,
) -> None:
    """
    POST the unified SessionResponse payload to Musa's webhook endpoint.

    Payload shape is IDENTICAL to GET /status response so Musa can use
    the same deserialisation logic for both polling and push, plus two
    extra fields (PAR-174): is_retry / resend_count. Every call from
    process_musa_session leaves is_retry at its False default — only a
    manual admin resend (resend_webhook_for_session, below) passes True —
    so Musa can unambiguously tell an original delivery from a replay and
    never mistake a resend for a second, distinct event.
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
        "is_retry": is_retry,
        "resend_count": resend_count,
    }
    headers = {
        "x-api-key": webhook_token,
        "Content-Type": "application/json",
    }
    status_code: Optional[int] = None
    delivery_error: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(webhook_url, json=payload, headers=headers)
        status_code = resp.status_code
        if resp.status_code == 200:
            logger.info("[MUSA] Webhook delivered session=%s", session_id)
        else:
            delivery_error = f"non-200 status {resp.status_code}: {resp.text[:200]}"
            logger.error(
                "[MUSA] Webhook non-200 session=%s status=%d body=%s",
                session_id, resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        # Never raise — Musa has status polling as fallback
        delivery_error = str(exc)[:500]
        logger.error("[MUSA] Webhook exception session=%s: %s", session_id, exc)

    # PAR-174: persist the outcome of this attempt so the admin UI can show
    # *why* a webhook needs resending instead of only a log line no one
    # sees. Best-effort — a failure here must not affect Musa's delivery
    # (already sent above) or bubble up past this function.
    try:
        attempted_at = datetime.now(timezone.utc).isoformat()
        if status_code == 200:
            # webhook_delivered_at (set below) is deliberately "most recent
            # success" — every resend overwrites it, which is the behaviour the
            # admin UI wants and which existing tests pin. The side effect is
            # that the FIRST delivery time is destroyed by the first resend, so
            # stamp it once into its own column here.
            #
            # The .is_(..., "null") filter IS the once-only guard: the first
            # successful delivery matches and writes, every later one matches
            # zero rows and is a no-op. Done as its own statement rather than
            # reading the row first and deciding in Python — _send_webhook has
            # no prior row state in scope on either call path, so that would
            # mean an extra round-trip AND a read-then-write race. Runs before
            # the main persist so the outcome write below stays the last word.
            get_supabase().table("musa_sessions").update(
                {"webhook_first_delivered_at": attempted_at}
            ).eq("session_id", session_id).is_(
                "webhook_first_delivered_at", "null"
            ).execute()

        update_fields = {
            "webhook_last_status_code": status_code,
            "webhook_last_attempted_at": attempted_at,
            "webhook_last_error": delivery_error,
        }
        if status_code == 200:
            update_fields["webhook_delivered_at"] = attempted_at
        if is_retry:
            update_fields["webhook_resend_count"] = resend_count
        get_supabase().table("musa_sessions").update(update_fields).eq(
            "session_id", session_id
        ).execute()
    except Exception:
        logger.exception(
            "[MUSA] Failed to persist webhook delivery status session=%s", session_id
        )


async def resend_webhook_for_session(session_id: str, base_url: Optional[str] = None) -> dict:
    """
    Manually re-deliver the webhook for an already-completed Musa session
    (PAR-174 Phase 1 — admin-triggered only; no automatic retry/backoff
    logic here, that's explicitly out of scope for this phase).

    Resending a session whose webhook already succeeded is allowed, not
    blocked. An admin choosing to resend is inherently a deliberate,
    infrequent action (e.g. Musa reports losing the original payload), and
    the is_retry/resend_count fields on the payload make every resend
    unambiguously a replay on Musa's side regardless of the prior outcome
    — that's what makes it safe to allow rather than a case to guard
    against by blocking it. A session that never finished processing
    (status="processing") IS blocked, since there is nothing coherent to
    resend yet.
    """
    supabase = get_supabase()
    result = (
        supabase.table("musa_sessions")
        .select("*")
        .eq("session_id", session_id)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")

    session = rows[0]
    status = session["status"]
    if status == "processing":
        raise HTTPException(
            status_code=409,
            detail="Session is still processing — nothing to resend yet",
        )

    resolved_base_url = base_url or API_BASE_URL
    status_url = f"{resolved_base_url}/api/musa/sessions/{session_id}/status"

    deal_id = session.get("deal_id")
    pdf_url = None
    if status == "complete" and deal_id:
        pdf_url = f"{API_BASE_URL}/v1/deals/{deal_id}/snapshot/pdf"

    resend_count = int(session.get("webhook_resend_count") or 0) + 1

    await _send_webhook(
        session_id=session_id,
        venture_name=session["venture_name"],
        venture_country=session.get("venture_country", ""),
        status=status,
        status_url=status_url,
        pdf_url=pdf_url,
        error_message=session.get("error_message"),
        created_at=session.get("created_at"),
        completed_at=session.get("completed_at"),
        is_retry=True,
        resend_count=resend_count,
    )

    refreshed = (
        supabase.table("musa_sessions")
        .select("webhook_last_status_code, webhook_delivered_at, webhook_resend_count")
        .eq("session_id", session_id)
        .execute()
    )
    refreshed_rows = refreshed.data or []
    refreshed_row = refreshed_rows[0] if refreshed_rows else {}

    return {
        "session_id": session_id,
        "status": status,
        "is_retry": True,
        "resend_count": refreshed_row.get("webhook_resend_count", resend_count),
        "webhook_status_code": refreshed_row.get("webhook_last_status_code"),
        "webhook_delivered": refreshed_row.get("webhook_delivered_at") is not None,
    }


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

    # PAR-242: pre-fill what's already resolvable at this exact point in the
    # flow (the deal record) rather than asking anyone to retype it. Only the
    # deal's own name/company_name is available here — no separate org/account
    # table with a registration or contact email exists for a Musa-originated
    # deal at this point (the deal's `created_by`/`user_id` links to `profiles`,
    # but Musa-created deals frequently have no signed-in Parity user attached,
    # so that lookup would silently return nothing for the common case; not
    # guessed at). Best-effort: a lookup failure must not block the existing
    # parser_requests insert/notify above.
    deal_name: Optional[str] = None
    try:
        deal = DealsRepo().get_deal(deal_id)
        if deal:
            deal_name = deal.get("company_name") or deal.get("name")
    except Exception:
        logger.exception(
            "[MUSA] Failed to look up deal for parser-request pre-fill deal_id=%s", deal_id
        )

    await _notify_parser_request(
        session_id=session_id,
        deal_id=deal_id,
        deal_name=deal_name,
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
    deal_name: Optional[str] = None,
) -> None:
    """
    Email the team that a Musa file failed with an unsupported/unparseable
    format, via the existing Next.js /api/request-parser endpoint (which
    owns the Resend integration — the Python backend has no email creds of
    its own). Tags the request partner="musa" so the route skips its
    pds_parser_requests insert (this path already wrote to parser_requests
    directly, just above) and the email is the only thing left to do here.

    deal_name (PAR-242): whatever was resolvable from the deal record at the
    detection point (see caller) — passed through so the notification names
    the actual deal, not just its opaque UUID. None when not resolvable;
    the frontend/email template renders that as "—", not a guess.

    Best-effort only: this must never affect musa_sessions state or the
    webhook Musa actually depends on.
    """
    notify_url = f"{PARITY_FRONTEND_URL}/api/request-parser"

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
                    "deal_name": deal_name,
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

    # PAR-200: declared before anything in the try below can raise, so the
    # outer except (a genuine setup-phase failure, e.g. get_supabase()
    # itself failing) can always reference it safely rather than risking a
    # NameError masked as a "failed to persist" log line.
    document_failures: List[Dict[str, Any]] = []

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

                # PAR-200: process_document_background never raises on a
                # genuine per-document parse failure — it catches every
                # exception internally (CurrencyMismatchError,
                # InvalidSchemaError, IngestionTimeoutError, and a trailing
                # bare Exception) and records the real outcome on the
                # document's own row via _update_failed(). Its return type
                # is -> None either way, so a clean return here does NOT
                # mean success. Query the row it just wrote instead of
                # assuming one — this is the actual bug: succeeded_count
                # used to increment unconditionally at this point.
                doc_rows = docs_repo.select_eq("id", document_id)
                doc_row = doc_rows[0] if doc_rows else {}
                doc_status = doc_row.get("status")

                if doc_status == "completed":
                    succeeded_count += 1
                else:
                    doc_next_action = doc_row.get("next_action")
                    doc_error_message = doc_row.get("error_message") or (
                        f"Document ended in status={doc_status!r} with no "
                        f"recorded error_message"
                    )
                    document_failures.append({
                        "filename": file_name or url,
                        "error_type": doc_row.get("error_type"),
                        "error_message": doc_error_message,
                        "next_action": doc_next_action,
                    })
                    # Same request_parser vs. everything-else split the old
                    # except-block below used, now driven by the real
                    # next_action _update_failed already computed (it
                    # already distinguishes unsupported-format from
                    # currency/CSV/timeout issues) instead of re-guessing
                    # from exception text that was never reachable here.
                    if doc_next_action == "request_parser":
                        unrecognized_count += 1
                        await _record_unrecognized_document(
                            session_id=session_id,
                            deal_id=deal_id,
                            venture_country=venture_country,
                            document_url=url,
                            error_message=doc_error_message,
                            storage_path=raw_storage_path,
                        )
                    elif other_failure is None:
                        other_failure = RuntimeError(doc_error_message)

            except Exception as doc_exc:
                # Unlike the branch above, this except block catches a
                # genuine exception from the orchestrator's OWN code around
                # process_document_background (e.g. _download_file network
                # errors, docs_repo.create_document failing) — not a parse
                # failure, since that path never raises here (see above).
                # Unreachable for parse/format failures; kept for these
                # real, different failure modes, unchanged in behavior.
                logger.warning(
                    "[MUSA] doc %d/%d failed session=%s url=%.60s: %s",
                    i + 1, len(documents), session_id, url, doc_exc,
                )
                document_failures.append({
                    "filename": file_name or url,
                    "error_type": doc_exc.__class__.__name__,
                    "error_message": str(doc_exc),
                    "next_action": None,
                })
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
            # failure webhook. status/completed_at deliberately untouched
            # (still "processing") — that timing is PAR-62's design, not
            # changed here. PAR-200: still write the real per-document
            # detail now, purely additive, so the admin UI has something
            # during the 24h window instead of nothing until force-close.
            if document_failures:
                try:
                    supabase.table("musa_sessions").update(
                        {"document_failures": document_failures}
                    ).eq("session_id", session_id).execute()
                except Exception:
                    logger.exception(
                        "[MUSA] Failed to persist document_failures session=%s", session_id
                    )
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
            {
                "status": "complete",
                "completed_at": completed_at,
                "error_message": partial_note,
                # PAR-200: real per-document reasons behind partial_note's
                # count, not just the count itself. None (not []) when
                # nothing failed, so a fully-successful session reads as
                # "no failure detail" rather than "checked, found none".
                "document_failures": document_failures or None,
            }
        ).eq("session_id", session_id).execute()

        pdf_url = f"{API_BASE_URL}/v1/deals/{deal_id}/snapshot/pdf"

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
                    # PAR-200: real per-document reasons, if this failure
                    # came from the loop (other_failure re-raised, or
                    # request_parser-classified documents that still left
                    # the whole batch at 0 successes). Empty/undefined for
                    # a genuine setup-phase failure before the loop ran.
                    "document_failures": document_failures or None,
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
