from __future__ import annotations

import os
import uuid
import logging
from pathlib import Path

from typing import Optional

from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from app.analytics import run_analytics
from app.models import ExtractionResult
from app.extractors.mpesa_extractor import extract_mpesa_csv
from app.extractors.pdf_type_detector import is_scanned_pdf
from app.extractors.docai_extractor import extract_with_docai
from app.extractors.pdf_document import PDFLockedError
from app.normaliser import normalise_all

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Parity Ingestion Service",
    version="1.0.0-phase3",
    description="Phase 1+3: raw extraction + normalisation (integer cents, ISO dates).",
)

_UPLOAD_DIR = Path("/tmp/parity-ingestion/uploads")
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# In-memory result store — intentionally stateless across restarts (Phase 1)
_results: dict[str, ExtractionResult] = {}


@app.get("/")
def root():
    return {"status": "ok", "service": "parity-ingestion"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "parity-ingestion", "version": "1.0.0-phase3"}


@app.post("/v1/ingest/upload")
async def upload(file: UploadFile = File(...), password: Optional[str] = Form(None)):
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()

    if ext not in (".pdf", ".csv"):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Accepted: .pdf, .csv (use /v1/ingest/excel for .xlsx)",
        )

    # Write to temp location
    result_id = str(uuid.uuid4())
    dest = _UPLOAD_DIR / f"{result_id}{ext}"
    content = await file.read()
    dest.write_bytes(content)

    try:
        if ext == ".pdf":
            from app.extractors.router import (
                route_extract,
                PASSWORD_REQUIRED_RESPONSE,
                PASSWORD_INCORRECT_RESPONSE,
            )

            # PAR-69: password is a per-request field, never persisted — not
            # written to `dest`, `_results`, or any log line below. A locked
            # PDF re-uploaded later must supply it again. `is_scanned_pdf`
            # runs first (decides OCR vs. text routing) and needs the same
            # password to even open a locked file, so it shares the same
            # `PDFLockedError` signal `route_extract()` uses below.
            try:
                scanned = is_scanned_pdf(str(dest), password=password)
            except PDFLockedError:
                resp = PASSWORD_INCORRECT_RESPONSE if password else PASSWORD_REQUIRED_RESPONSE
                raise HTTPException(status_code=401, detail=resp["message"])

            if scanned:
                result = extract_with_docai(str(dest), doc_id=result_id, filename=filename)
            else:
                result = route_extract(str(dest), password=password)
                if isinstance(result, dict) and result.get("status") == "UNSUPPORTED_FORMAT":
                    raise HTTPException(
                        status_code=415,
                        detail=result.get("message", "Bank format not recognised."),
                    )
                if isinstance(result, dict) and result.get("status") in (
                    "PASSWORD_REQUIRED",
                    "PASSWORD_INCORRECT",
                ):
                    raise HTTPException(
                        status_code=401,
                        detail=result.get("message", "This PDF requires a password."),
                    )
        else:
            result = extract_mpesa_csv(str(dest))
        normalise_all(result)
        rows = result.normalised_transactions or []
        logger.info("[INGESTION] Parsed rows: %d", len(rows))
    except HTTPException:
        # Preserve the intended status code (415 unsupported, 401 password)
        # instead of letting the generic handler below flatten it to a 500.
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result.result_id = result_id
    result.source_file = filename  # return original name, not temp path
    _results[result_id] = result

    result_dict = result.model_dump()
    result_dict["analytics"] = run_analytics(result.raw_transactions)
    # raw_transactions is only needed locally (tests/result store).
    # Drop it from the HTTP response to keep payload small for large statements.
    result_dict.pop("raw_transactions", None)
    return result_dict


@app.post("/v1/ingest/excel")
async def ingest_excel(file: UploadFile = File(...)):
    """Excel-only: large workbooks are parsed here (GCP) — not on the Render API."""
    filename = file.filename or "upload.xlsx"
    ext = Path(filename).suffix.lower()
    if ext not in (".xlsx", ".xlsm"):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Accepted: .xlsx, .xlsm",
        )

    result_id = str(uuid.uuid4())
    dest = _UPLOAD_DIR / f"{result_id}{ext}"
    content = await file.read()
    dest.write_bytes(content)

    try:
        from app.parsers.xlsx_parser import extraction_result_from_xlsx_bytes

        deal_currency = os.getenv("DEFAULT_DEAL_CURRENCY", "KES")
        result, _raw_hash = extraction_result_from_xlsx_bytes(
            content, result_id, deal_currency, filename
        )
        normalise_all(result)
        rows = result.normalised_transactions or []
        logger.info("[INGESTION] Parsed rows: %d", len(rows))
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result.result_id = result_id
    result.source_file = filename
    _results[result_id] = result

    result_dict = result.model_dump()
    result_dict["analytics"] = run_analytics(result.raw_transactions)
    result_dict.pop("raw_transactions", None)
    return result_dict


@app.post("/v1/ingest/audited-financials")
async def ingest_audited_financials(file: UploadFile = File(...)):
    """
    Extract structured financial data from an audited financial statements PDF.

    Accepts PDF files.  For native (text-layer) PDFs uses coordinate-based
    extraction; for scanned (image-only) PDFs falls back to Tesseract OCR.
    Returns all income statement, balance sheet, cash flow, and notes fields
    ready for storage in pds_audited_financials.
    """
    filename = file.filename or "financials.pdf"
    ext = Path(filename).suffix.lower()
    if ext != ".pdf":
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Use /v1/ingest/audited-financials/tabular for CSV/Excel.",
        )

    result_id = str(uuid.uuid4())
    dest = _UPLOAD_DIR / f"{result_id}{ext}"
    content = await file.read()
    dest.write_bytes(content)

    try:
        from app.extractors.audited_financials_extractor import (
            extract_audited_financials,
            extract_audited_financials_from_ocr,
        )

        if is_scanned_pdf(str(dest)):
            logger.info("[AUDITED] Scanned PDF detected — activating OCR for %s", filename)
            data = extract_audited_financials_from_ocr(str(dest))
        else:
            data = extract_audited_financials(str(dest))

        logger.info(
            "[AUDITED] Extracted %s FY%s — confidence=%.1f%% method=%s",
            data.get("company_name"),
            data.get("financial_year"),
            float(data.get("extraction_confidence", 0)),
            data.get("extraction_method"),
        )
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        dest.unlink(missing_ok=True)

    # Return the extraction dict directly — caller stores in pds_audited_financials
    return data


@app.post("/v1/ingest/audited-financials/tabular")
async def ingest_audited_financials_tabular(file: UploadFile = File(...)):
    """
    Extract financial statement fields from a CSV or Excel file.

    Accepts .csv, .xlsx, .xls.  Applies label-based extraction and returns
    the same dict shape as /v1/ingest/audited-financials so callers are
    format-agnostic.  Confidence is capped lower (60/65) to prompt the
    analyst confirmation form.
    """
    filename = file.filename or "financials.csv"
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Accepted: .csv, .xlsx, .xls",
        )

    result_id = str(uuid.uuid4())
    dest = _UPLOAD_DIR / f"{result_id}{ext}"
    content = await file.read()
    dest.write_bytes(content)

    try:
        from app.extractors.tabular_financials_extractor import (
            extract_audited_financials_from_csv,
            extract_audited_financials_from_excel,
        )

        if ext == ".csv":
            data = extract_audited_financials_from_csv(str(dest))
        else:
            data = extract_audited_financials_from_excel(str(dest))
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        dest.unlink(missing_ok=True)

    return data


@app.get("/v1/ingest/result/{result_id}", response_model=ExtractionResult)
def get_result(result_id: str) -> ExtractionResult:
    result = _results.get(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return result
