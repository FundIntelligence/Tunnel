"""
Client for parity-ingestion microservice.
When PARITY_INGESTION_URL is set, PDF and XLSX files are sent to parity-ingestion for
bank-specific extraction. CSV remains parsed locally unless routed otherwise.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Tuple

import httpx


class IngestionTimeoutError(Exception):
    """Raised when the HTTP client times out waiting for parity-ingestion.

    partial_data, if present, contains a JSON result payload (or a best-effort
    partial payload) returned by parity-ingestion that we can attempt to
    convert into rows.
    """

    def __init__(self, message: str, *, partial_data: Any = None):
        super().__init__(message)
        self.partial_data = partial_data


logger = logging.getLogger(__name__)

from .common import canonical_hash, compute_txn_id, normalize_descriptor, sort_rows
from .errors import InvalidSchemaError


PARITY_INGESTION_URL = os.getenv("PARITY_INGESTION_URL", "").rstrip("/")

import io
import re as _re

_INLINE_CURRENCY_PAT = _re.compile(
    r'(?:Currency|Account\s+Currency)[:\s]+([A-Z]{3})\b'
    r'|Available\s+Balance:\s+([A-Z]{3})\b'
    r'|\b(KES|UGX|RWF|TZS|NGN|GHS|ETB|ZAR|USD|EUR|GBP)\s+[\d,]+',
    _re.IGNORECASE,
)
_KNOWN_CURRENCIES = {'KES', 'UGX', 'RWF', 'TZS', 'NGN', 'GHS', 'ETB', 'ZAR', 'USD', 'EUR', 'GBP'}


def _detect_currency_from_bytes(file_bytes: bytes) -> Optional[str]:
    """
    Detect ISO 4217 currency code from first 2 pages of a PDF given as raw bytes.
    Returns None if undetermined. Never raises.
    """
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            text = ' '.join(p.extract_text() or '' for p in pdf.pages[:2])
        m = _INLINE_CURRENCY_PAT.search(text[:2000])
        if m:
            code = next(g for g in m.groups() if g).upper()
            if code in _KNOWN_CURRENCIES:
                return code
    except Exception:
        pass
    return None


def _mime_for_upload(file_name: str) -> str:
    n = (file_name or "").lower()
    if n.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if n.endswith(".xlsm"):
        return "application/vnd.ms-excel.sheet.macroEnabled.12"
    return "application/pdf"


def _ingest_upload_url(file_name: str) -> str:
    """Excel is parsed on GCP only — dedicated route to avoid loading openpyxl on Render."""
    n = (file_name or "").lower()
    if n.endswith((".xlsx", ".xlsm")):
        return f"{PARITY_INGESTION_URL}/v1/ingest/excel"
    return f"{PARITY_INGESTION_URL}/v1/ingest/upload"


def _parity_result_to_rows(
    result: dict,
    document_id: str,
) -> List[Dict[str, Any]]:
    """Convert parity-ingestion ExtractionResult to backend row format."""
    rows: List[Dict[str, Any]] = []
    normalised = result.get("normalised_transactions") or []

    for n in normalised:
        debit = n.get("debit_cents") or 0
        credit = n.get("credit_cents") or 0
        signed_cents = credit - debit
        if signed_cents == 0:
            continue
        txn_date = n.get("date")
        if not txn_date:
            continue
        desc = n.get("description") or ""
        row_obj: Dict[str, Any] = {
            "txn_date": txn_date,
            "signed_amount_cents": signed_cents,
            "abs_amount_cents": abs(signed_cents),
            "raw_descriptor": desc,
            "parsed_descriptor": desc.strip(),
            "normalized_descriptor": normalize_descriptor(desc),
            # Per-document account_id enables transfer detection — see PAR-30.
            "account_id": str(document_id),
        }
        row_obj["txn_id"] = compute_txn_id(row_obj, document_id)
        rows.append(row_obj)

    return rows


def parse_via_parity_ingestion(
    file_bytes: bytes,
    file_name: str,
    document_id: str,
    deal_currency: str,
) -> Tuple[List[Dict[str, Any]], str, str, Dict[str, Any]]:
    """
    POST PDF or XLSX to parity-ingestion, convert result to backend rows.
    Returns (rows, raw_transaction_hash, currency_detection, analytics).
    """
    fname = file_name or "upload.pdf"
    url = _ingest_upload_url(fname)
    files = {"file": (fname, file_bytes, _mime_for_upload(fname))}

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(600.0)) as client:
            try:
                resp = client.post(url, files=files)
            except httpx.ReadTimeout as exc:
                elapsed = time.perf_counter() - t0
                partial_result = None
                # httpx may attach a response; if it does, attempt best-effort JSON extraction.
                maybe_resp = getattr(exc, "response", None)
                if maybe_resp is not None:
                    try:
                        partial_result = maybe_resp.json()
                    except Exception:
                        partial_result = None
                raise IngestionTimeoutError(
                    f"Read timeout calling parity-ingestion for document_id={document_id} "
                    f"after {elapsed:.2f}s",
                    partial_data=partial_result,
                ) from exc
            except httpx.TimeoutException as exc:
                elapsed = time.perf_counter() - t0
                partial_result = None
                maybe_resp = getattr(exc, "response", None)
                if maybe_resp is not None:
                    try:
                        partial_result = maybe_resp.json()
                    except Exception:
                        partial_result = None
                raise IngestionTimeoutError(
                    f"Timeout calling parity-ingestion for document_id={document_id} "
                    f"after {elapsed:.2f}s",
                    partial_data=partial_result,
                ) from exc

        # We got a response; try to parse JSON regardless of status code.
        result: Any = None
        if resp.status_code == 415:
            # Before giving up, try inline parsers that run directly on the Render
            # worker (pdfplumber only — no OCR).  This covers KCB iBANK Online PDFs
            # that the deployed parity-ingestion service may not yet recognise.
            inline_rows = _try_inline_parse(file_bytes, fname, document_id)
            if inline_rows:
                logger.info(
                    "[BACKEND] Inline parser succeeded for document_id=%s rows=%d",
                    document_id,
                    len(inline_rows),
                )
                rows_sorted = sort_rows(inline_rows)
                raw_hash = canonical_hash(rows_sorted)
                detected_currency = _detect_currency_from_bytes(file_bytes)
                return rows_sorted, raw_hash, detected_currency, {}

            try:
                detail = resp.json().get("detail", "Bank format not recognised by parity-ingestion.")
            except Exception:
                detail = "Bank format not recognised by parity-ingestion."
            raise InvalidSchemaError(detail)

        try:
            result = resp.json()
        except Exception:
            # If we can't read JSON, keep previous behavior.
            resp.raise_for_status()

        if resp.status_code >= 400:
            detail: Any = None
            if isinstance(result, dict):
                detail = result.get("detail")
            if isinstance(detail, list):
                msg = str(detail)
            else:
                msg = str(detail) if detail else f"parity-ingestion HTTP {resp.status_code}"
            raise InvalidSchemaError(msg)

        # If the service says unsupported but it still included transactions, prefer transactions.
        if isinstance(result, dict) and result.get("status") == "UNSUPPORTED_FORMAT":
            tentative_rows = _parity_result_to_rows(result, document_id)
            if not tentative_rows:
                raise InvalidSchemaError(result.get("message", "Bank format not recognised."))

        rows = _parity_result_to_rows(result, document_id)
        if not rows:
            raise InvalidSchemaError("No valid transactions extracted via parity-ingestion")
        logger.info("[BACKEND] Rows received from ingestion: %d", len(rows))

        rows_sorted = sort_rows(rows)
        raw_hash = canonical_hash(rows_sorted)
        currency_detection = result.get("currency") or "unknown"
        analytics = result.get("analytics") or {}
        return rows_sorted, raw_hash, currency_detection, analytics

    except IngestionTimeoutError as exc:
        # NEW: best-effort salvage if timeout occurred but we have partial payload.
        partial_result = getattr(exc, "partial_data", None)
        if isinstance(partial_result, dict):
            try:
                rows = _parity_result_to_rows(partial_result, document_id)
                if rows:
                    logger.warning(
                        "Partial ingestion used due to timeout for document_id=%s (rows=%d)",
                        document_id,
                        len(rows),
                    )
                    logger.info("[BACKEND] Rows received from ingestion: %d", len(rows))
                    rows_sorted = sort_rows(rows)
                    raw_hash = canonical_hash(rows_sorted)
                    currency_detection = partial_result.get("currency") or "unknown"
                    analytics = partial_result.get("analytics") or {}
                    return rows_sorted, raw_hash, currency_detection, analytics
            except Exception:
                # If salvage fails, fall back to raising the timeout.
                pass
        raise


def _try_inline_parse(
    file_bytes: bytes,
    file_name: str,
    document_id: str,
) -> list:
    """
    Attempt to parse a PDF that parity-ingestion rejected (415).

    Currently handles KCB iBANK Online format.
    Returns a list of backend-format rows, or [] if format not recognised.
    """
    try:
        from .kcb_inline import detect_kcb_online_bytes, extract_kcb_online_rows
        if detect_kcb_online_bytes(file_bytes):
            logger.info("[INLINE] Detected KCB Online format — parsing inline")
            return extract_kcb_online_rows(file_bytes, document_id)
    except Exception as exc:
        logger.warning("[INLINE] KCB inline parse failed: %s", exc)

    return []


# Backward-compatible name for imports
parse_pdf_via_parity_ingestion = parse_via_parity_ingestion
