import asyncio
import logging
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI

from ..config import SCHEMA_VERSION, CONFIG_VERSION
from ..parsing import parse_file
from ..parsing.errors import InvalidSchemaError, CurrencyMismatchError
from ..parsing.parity_ingestion_client import IngestionTimeoutError
from ..parsing.common import canonical_hash, sort_rows
from ..errors import is_dev_diagnostics
from ..db.repositories import (
    AnalysisRunsRepository,
    DocumentsRepository,
    RawTransactionsRepository,
)

logger = logging.getLogger(__name__)
INSERT_CHUNK_SIZE = 500

# Stuck documents: processing longer than this are marked failed on API boot.
STUCK_PROCESSING_MINUTES = 20
_STUCK_SELECT_LIMIT = 50_000

# Ingestion stages (must match exactly for diagnostics)
STAGE_FILE_RECEIVED = "FILE_RECEIVED"
STAGE_PARSE_START = "PARSE_START"
STAGE_PARSE_DONE = "PARSE_DONE"
STAGE_SCHEMA_VALIDATED = "SCHEMA_VALIDATED"
STAGE_NORMALIZATION_DONE = "NORMALIZATION_DONE"
STAGE_DB_INSERT_START = "DB_INSERT_START"
STAGE_DB_INSERT_DONE = "DB_INSERT_DONE"
STAGE_STATUS_COMPLETED = "STATUS_COMPLETED"


class IngestionResult(Dict[str, Any]):
    pass


class IngestionService:
    """
    Deterministic ingestion orchestrator for v1.

    Responsibilities:
    - Parse file deterministically (csv/xlsx/pdf) into canonical rows
    - Persist document and raw transactions via repositories
    - Return raw_transaction_hash and currency_detection
    """

    def __init__(
        self,
        documents_repo: DocumentsRepository,
        raw_tx_repo: RawTransactionsRepository,
        analysis_repo: Optional[AnalysisRunsRepository] = None,
    ):
        self.documents_repo = documents_repo
        self.raw_tx_repo = raw_tx_repo
        self.analysis_repo = analysis_repo

    def _insert_rows_in_chunks(self, rows: list[Dict[str, Any]]) -> int:
        """Insert parsed rows in chunks to avoid per-request row limits."""
        if not rows:
            return 0
        inserted_count = 0
        for i in range(0, len(rows), INSERT_CHUNK_SIZE):
            chunk = rows[i : i + INSERT_CHUNK_SIZE]
            self.raw_tx_repo.insert_batch(chunk)
            inserted_count += len(chunk)
        return inserted_count

    def _assert_row_integrity(self, parsed_rows: list[Dict[str, Any]], inserted_count: int) -> None:
        parsed_count = len(parsed_rows)
        if parsed_count != inserted_count:
            raise ValueError(
                f"ROW COUNT MISMATCH: parsed={parsed_count}, inserted={inserted_count}"
            )

    def ingest(
        self,
        *,
        deal_id: str,
        created_by: str,
        file_bytes: bytes,
        file_name: str,
        file_type: str,
        deal_currency: str,
    ) -> IngestionResult:
        document_id = str(uuid.uuid4())

        # Parse deterministically
        parse_start = time.perf_counter()
        try:
            rows, raw_hash, currency_detection, analytics = parse_file(
                file_bytes, file_type, document_id, deal_currency, file_name=file_name or ""
            )
        except CurrencyMismatchError:
            raise
        except InvalidSchemaError:
            raise
        except Exception as exc:
            raise InvalidSchemaError(str(exc)) from exc
        parse_end = time.perf_counter()
        parse_ms = int((parse_end - parse_start) * 1000)

        # Persist document
        document = {
            "id": document_id,
            "deal_id": deal_id,
            "storage_url": f"inline://{file_name}",
            "file_type": file_type.lower(),
            "status": "completed",
            "currency_detected": None if currency_detection == "unknown" else currency_detection,
            "currency_mismatch": False,
            "created_by": created_by,
        }
        self.documents_repo.create_document(document)

        # Persist rows (abs_amount_cents is already computed by the parser —
        # NOT a DB-generated column despite the old assumption here; popping
        # it left every transaction's abs_amount_cents permanently NULL,
        # silently zeroing outflow composition and loan activity totals
        # platform-wide. See migration backfilling existing NULL rows.)
        for r in rows:
            r["document_id"] = document_id
            r["deal_id"] = deal_id

        db_insert_start = time.perf_counter()
        logger.info("[DB INSERT] Rows to insert: %d", len(rows))
        inserted_count = self._insert_rows_in_chunks(rows)
        logger.info("[DB INSERT] Rows inserted: %d", inserted_count)
        self._assert_row_integrity(rows, inserted_count)
        db_insert_end = time.perf_counter()
        insert_ms = int((db_insert_end - db_insert_start) * 1000)

        logger.info("[INGEST] rows=%d parse_ms=%d insert_ms=%d", len(rows), parse_ms, insert_ms)

        # Optional: seed analysis_runs skeleton (LIVE_DRAFT placeholder without metrics)
        if self.analysis_repo:
            self.analysis_repo.insert_run(
                {
                    "id": str(uuid.uuid4()),
                    "deal_id": deal_id,
                    "state": "LIVE_DRAFT",
                    "schema_version": SCHEMA_VERSION,
                    "config_version": CONFIG_VERSION,
                    "run_trigger": "parse_complete",
                    "non_transfer_abs_total_cents": 0,
                    "classified_abs_total_cents": 0,
                    "coverage_pct_bp": 0,
                    "missing_month_penalty_bp": 0,
                    "override_penalty_bp": 0,
                    "reconciliation_pct_bp": None,
                    "base_confidence_bp": 0,
                    "final_confidence_bp": 0,
                    "missing_month_count": 0,
                    "reconciliation_status": "NOT_RUN",
                    "tier": "Low",
                    "tier_capped": False,
                    "raw_transaction_hash": raw_hash,
                    "transfer_links_hash": canonical_hash([]),
                    "entities_hash": canonical_hash([]),
                    "overrides_hash": canonical_hash([]),
                }
            )

        return {
            "document_id": document_id,
            "rows_count": len(rows),
            "raw_transaction_hash": raw_hash,
            "currency_detection": currency_detection,
        }

    def _update_failed(
        self,
        document_id: str,
        error_type: str,
        error_message: str,
        stage: str,
        next_action: str,
        currency_mismatch: bool = False,
        exc: Optional[Exception] = None,
    ) -> None:
        tb_str = traceback.format_exc() if (is_dev_diagnostics() and exc) else None
        try:
            self.documents_repo.update_status(
                document_id,
                "failed",
                currency_mismatch=currency_mismatch,
                error_message=error_message,
                error_type=error_type,
                error_stage=stage,
                next_action=next_action,
            )
        except Exception:
            pass
        if tb_str:
            logger.debug("[INGEST] traceback (dev): %s", tb_str)

    def process_document_background(
        self,
        *,
        document_id: str,
        deal_id: str,
        created_by: str,
        file_bytes: bytes,
        file_name: str,
        file_type: str,
        deal_currency: str,
    ) -> None:
        """
        Process document in background. Document must already exist with status=processing.
        On success: updates status=completed, inserts rows, inserts analysis run.
        On failure: updates status=failed with structured error taxonomy.
        """
        stage = STAGE_FILE_RECEIVED
        try:
            stage = STAGE_PARSE_START
            logger.info("[INGEST] stage=%s document_id=%s", stage, document_id)
            parse_start = time.perf_counter()
            parse_result = parse_file(
                file_bytes, file_type, document_id, deal_currency, file_name=file_name or ""
            )
            if len(parse_result) == 4:
                rows, raw_hash, currency_detection, analytics = parse_result
            else:
                rows, raw_hash, currency_detection = parse_result
                analytics = {}
            parse_end = time.perf_counter()
            parse_ms = int((parse_end - parse_start) * 1000)
            stage = STAGE_PARSE_DONE
            logger.info("[INGEST] stage=%s rows=%d parse_ms=%d", stage, len(rows), parse_ms)

            stage = STAGE_SCHEMA_VALIDATED
            logger.info("[INGEST] stage=%s rows=%d", stage, len(rows))

            stage = STAGE_NORMALIZATION_DONE
            for r in rows:
                r["document_id"] = document_id
                r["deal_id"] = deal_id

            stage = STAGE_DB_INSERT_START
            logger.info("[INGEST] stage=%s rows=%d", stage, len(rows))
            db_insert_start = time.perf_counter()
            logger.info("[DB INSERT] Rows to insert: %d", len(rows))
            inserted_count = self._insert_rows_in_chunks(rows)
            logger.info("[DB INSERT] Rows inserted: %d", inserted_count)
            self._assert_row_integrity(rows, inserted_count)
            db_insert_end = time.perf_counter()
            insert_ms = int((db_insert_end - db_insert_start) * 1000)
            stage = STAGE_DB_INSERT_DONE
            logger.info("[INGEST] stage=%s rows=%d insert_ms=%d", stage, len(rows), insert_ms)

            combined_analytics = dict(analytics) if analytics else {}
            combined_analytics.update(
                {
                    "rows_parsed": len(rows),
                    "rows_inserted": inserted_count,
                    "integrity_verified": len(rows) == inserted_count,
                }
            )
            self.documents_repo.update_status(
                document_id,
                "completed",
                currency_mismatch=False,
                analytics=combined_analytics,
                currency_detected=currency_detection if currency_detection != "unknown" else None,
            )
            if currency_detection and currency_detection != "unknown":
                try:
                    from ..db.supabase_repositories import DealsRepo
                    DealsRepo().set_currency_if_unset(deal_id, currency_detection)
                except Exception as _exc:
                    logger.warning("[INGEST] currency write to deal failed (non-fatal): %s", _exc)
            stage = STAGE_STATUS_COMPLETED

            if self.analysis_repo:
                self.analysis_repo.insert_run(
                    {
                        "id": str(uuid.uuid4()),
                        "deal_id": deal_id,
                        "state": "LIVE_DRAFT",
                        "schema_version": SCHEMA_VERSION,
                        "config_version": CONFIG_VERSION,
                        "run_trigger": "parse_complete",
                        "non_transfer_abs_total_cents": 0,
                        "classified_abs_total_cents": 0,
                        "coverage_pct_bp": 0,
                        "missing_month_penalty_bp": 0,
                        "override_penalty_bp": 0,
                        "reconciliation_pct_bp": None,
                        "base_confidence_bp": 0,
                        "final_confidence_bp": 0,
                        "missing_month_count": 0,
                        "reconciliation_status": "NOT_RUN",
                        "tier": "Low",
                        "tier_capped": False,
                        "raw_transaction_hash": raw_hash,
                        "transfer_links_hash": canonical_hash([]),
                        "entities_hash": canonical_hash([]),
                        "overrides_hash": canonical_hash([]),
                    }
                )

            logger.info("[INGEST] rows=%d parse_ms=%d insert_ms=%d", len(rows), parse_ms, insert_ms)
        except CurrencyMismatchError as exc:
            logger.warning("[INGEST] background currency mismatch stage=%s", stage)
            self._update_failed(
                document_id,
                error_type="CurrencyMismatchError",
                error_message=str(exc),
                stage=stage,
                next_action="fix_currency",
                currency_mismatch=True,
                exc=exc,
            )
        except InvalidSchemaError as exc:
            logger.warning("[INGEST] background invalid schema stage=%s: %s", stage, exc)
            currency_mismatch = "currency mismatch" in str(exc).lower()
            # Differentiate unsupported bank format (triggers parser-request flow on frontend)
            # from CSV schema errors (fix_csv_header) by examining message keywords.
            _emsg = str(exc).lower()
            _is_unsupported = any(
                kw in _emsg
                for kw in ("not recognised", "not recognized", "unsupported", "no valid transactions", "bank format")
            )
            self._update_failed(
                document_id,
                error_type="InvalidSchemaError",
                error_message=str(exc),
                stage=stage,
                next_action="request_parser" if _is_unsupported else "fix_csv_header",
                currency_mismatch=currency_mismatch,
                exc=exc,
            )
        except IngestionTimeoutError as exc:
            logger.error("Ingestion timeout for document %s after 300s", document_id)
            self._update_failed(
                document_id,
                error_type="ingestion_timeout",
                error_message=str(exc),
                stage=stage,
                next_action="retry_or_contact_support",
                currency_mismatch=False,
                exc=exc,
            )
        except Exception as exc:
            logger.exception("[INGEST] background failed stage=%s: %s", stage, exc)
            self._update_failed(
                document_id,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                stage=stage,
                next_action="retry_or_contact_support",
                currency_mismatch=False,
                exc=exc,
            )


def _parse_document_ts(value: Any) -> Optional[datetime]:
    """Parse Supabase timestamptz (ISO string or datetime) to UTC-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fail_stuck_processing_documents_sync() -> None:
    """
    Mark documents stuck in ``processing`` as failed if their reference time
    is older than :data:`STUCK_PROCESSING_MINUTES`.

    Uses ``updated_at`` when present on the row, otherwise ``created_at``
    (``pds_documents`` may only have ``created_at`` in some deployments).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_PROCESSING_MINUTES)
    from ..db.supabase_client import get_supabase
    from ..db.supabase_repositories import DocumentsRepo

    client = get_supabase()
    try:
        res = (
            client.table("pds_documents")
            .select("id,created_at,updated_at")
            .eq("status", "processing")
            .range(0, _STUCK_SELECT_LIMIT - 1)
            .execute()
        )
    except Exception as exc:
        # e.g. column ``updated_at`` missing — fall back to id + created_at only
        logger.warning(
            "[STARTUP] stuck-doc select with updated_at failed (%s); retrying without updated_at",
            exc,
        )
        res = (
            client.table("pds_documents")
            .select("id,created_at")
            .eq("status", "processing")
            .range(0, _STUCK_SELECT_LIMIT - 1)
            .execute()
        )

    rows = res.data or []
    docs_repo = DocumentsRepo()
    n_failed = 0
    for row in rows:
        ref_raw = row.get("updated_at") or row.get("created_at")
        ref = _parse_document_ts(ref_raw)
        if ref is None or ref >= cutoff:
            continue
        doc_id = row.get("id")
        if not doc_id:
            continue
        try:
            docs_repo.update_status(
                str(doc_id),
                "failed",
                error_type="ingestion_timeout",
                error_message=(
                    "Marked failed on startup: document remained in processing for more than "
                    f"{STUCK_PROCESSING_MINUTES} minutes."
                ),
                error_stage="PROCESSING",
                next_action="retry_or_contact_support",
            )
            n_failed += 1
            logger.info(
                "[STARTUP] marked stuck processing document %s as failed (ref=%s < cutoff=%s)",
                doc_id,
                ref_raw,
                cutoff.isoformat(),
            )
        except Exception as exc:
            logger.warning(
                "[STARTUP] could not mark stuck document %s failed: %s", doc_id, exc
            )

    if n_failed:
        logger.info("[STARTUP] fail_stuck_documents: updated %d document(s)", n_failed)


async def fail_stuck_processing_documents() -> None:
    """Async wrapper so startup does not block the event loop on DB I/O."""
    await asyncio.to_thread(_fail_stuck_processing_documents_sync)


def register_ingestion_startup(app: FastAPI) -> None:
    """Attach ingestion-related startup handlers (stuck document cleanup)."""
    from contextlib import asynccontextmanager

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan_with_ingestion(app: FastAPI):
        await fail_stuck_processing_documents()
        if original_lifespan is not None:
            async with original_lifespan(app):
                yield
        else:
            yield

    app.router.lifespan_context = lifespan_with_ingestion
