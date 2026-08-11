"""
Musa Ventures partner API.

Endpoints
---------
POST /api/musa/sessions
    Create a session with document URLs.  Returns immediately with
    status="processing"; background task handles download + ingestion.

GET  /api/musa/sessions/{session_id}/status
    Poll processing status.  Response shape is IDENTICAL to the POST
    response and to the webhook payload (SessionResponse).

GET  /api/musa/sessions/{session_id}/results
    Convenience endpoint that returns the full analytics JSON when
    status="complete".  Kept for direct inspection; the canonical
    integration path is status polling or webhook.

CRITICAL — SessionResponse is used in THREE places:
  1. POST /sessions response
  2. GET  /sessions/{id}/status response
  3. Webhook payload (musa_file_processor._send_webhook)
Any field change must be applied to all three.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel

from ..db.supabase_client import get_supabase
from ..db.supabase_repositories import DealsRepo, SnapshotsRepo
from ..core.snapshot_engine import decompress_canonical_json_if_needed
from .auth import require_musa_api_key
from .currency_utils import country_to_currency
from .musa_deploy_config import API_BASE_URL
from .musa_file_processor import process_musa_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/musa", tags=["musa"])


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class DocumentUpload(BaseModel):
    url: str
    file_type: Optional[str] = None  # "bank_statement", "mpesa", "audited_financials"
    date_from: Optional[str] = None  # ISO date format YYYY-MM-DD
    date_to: Optional[str] = None    # ISO date format YYYY-MM-DD


class CreateSessionRequest(BaseModel):
    venture_name: str
    venture_country: str
    document_urls: List[DocumentUpload]


class SessionResponse(BaseModel):
    """
    CRITICAL: This exact shape is used for:
    1. POST /api/musa/sessions response
    2. GET /api/musa/sessions/{id}/status response
    3. Webhook payload sent to Musa

    Do NOT modify this without updating all three uses.
    """
    session_id: str
    venture_name: str
    venture_country: str
    status: str  # "processing" | "complete" | "failed"
    status_url: str
    pdf_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str  # ISO 8601 format
    completed_at: Optional[str] = None  # ISO 8601 format


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _to_iso(value: Optional[str]) -> Optional[str]:
    """Convert various datetime formats to ISO 8601 UTC"""
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, AttributeError):
        return value


def _build_session_response(
    session_data: dict,
    deal_id: Optional[str] = None,
    base_url: Optional[str] = None,
) -> SessionResponse:
    """Build SessionResponse from database row"""
    if base_url is None:
        base_url = API_BASE_URL
    session_id = session_data["session_id"]
    status = session_data["status"]

    # Build status URL
    status_url = f"{base_url}/api/musa/sessions/{session_id}/status"

    # Build PDF URL if complete
    pdf_url = None
    if status == "complete" and deal_id:
        pdf_url = f"{base_url}/v1/deals/{deal_id}/snapshot/pdf"

    return SessionResponse(
        session_id=session_id,
        venture_name=session_data["venture_name"],
        venture_country=session_data.get("venture_country", ""),
        status=status,
        status_url=status_url,
        pdf_url=pdf_url,
        error_message=session_data.get("error_message"),
        created_at=_to_iso(session_data.get("created_at")) or "",
        completed_at=_to_iso(session_data.get("completed_at"))
    )


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: Request,
    body: CreateSessionRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(require_musa_api_key),
) -> SessionResponse:
    """
    Create a new Musa session with document URLs for processing.

    Flow:
    1. Create musa_sessions record (status=processing)
    2. Create pds_deals record
    3. Link session to deal
    4. Trigger background file processing
    5. Return session response immediately
    """
    session_id = str(uuid.uuid4())

    # Resolve currency from country — raises 422 immediately if unrecognised
    try:
        deal_currency = country_to_currency(body.venture_country)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # 1. Create deal
    try:
        deal = DealsRepo().create_deal({
            "id": str(uuid.uuid4()),
            "currency": deal_currency,
            "name": body.venture_name,
            "created_by": "00000000-0000-0000-0000-000000000001",  # Musa system user
        })
    except Exception:
        logger.exception("Failed to create deal for Musa session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to create deal")

    deal_id = deal.get("id")

    # 2. Create musa_sessions record
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        supabase = get_supabase()
        result = (
            supabase.table("musa_sessions")
            .insert({
                "session_id": session_id,
                "venture_id": session_id,
                "venture_name": body.venture_name,
                "venture_country": body.venture_country,
                "deal_id": deal_id,
                "status": "processing",
                "document_urls": [doc.model_dump() for doc in body.document_urls],
                "created_at": created_at,
            })
            .execute()
        )
        if not result.data:
            raise RuntimeError("Insert returned no data")

        session_data = result.data[0]

    except Exception as exc:
        _msg = str(exc)
        if "duplicate" in _msg.lower() or "unique" in _msg.lower():
            raise HTTPException(status_code=409, detail="Session already exists")
        logger.exception("Failed to insert musa_session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to create session")

    # 3. Build status URL — derive from the incoming request so status_url always
    #    points to the server that received this POST, not a hardcoded fallback.
    base_url = str(request.base_url).rstrip("/")
    status_url = f"{base_url}/api/musa/sessions/{session_id}/status"

    # 4. Trigger background processing
    background_tasks.add_task(
        process_musa_session,
        session_id=session_id,
        deal_id=deal_id,
        venture_name=body.venture_name,
        venture_country=body.venture_country,
        documents=[doc.model_dump() for doc in body.document_urls],
        status_url=status_url,
        created_at=created_at
    )

    # 5. Return response
    return SessionResponse(
        session_id=session_id,
        venture_name=body.venture_name,
        venture_country=body.venture_country,
        status="processing",
        status_url=status_url,
        pdf_url=None,
        error_message=None,
        created_at=created_at,
        completed_at=None
    )


@router.get("/sessions/{session_id}/status", response_model=SessionResponse)
def get_session_status(
    request: Request,
    session_id: str,
    _: bool = Depends(require_musa_api_key),
) -> SessionResponse:
    """
    Get current status of a Musa session.

    CRITICAL: Response shape MUST be identical to:
    - POST /sessions response
    - Webhook payload
    """
    try:
        supabase = get_supabase()
        result = (
            supabase.table("musa_sessions")
            .select("*")
            .eq("session_id", session_id)
            .execute()
        )
    except Exception:
        logger.exception("Failed to query musa_session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve session")

    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = rows[0]
    return _build_session_response(
        session_data,
        session_data.get("deal_id"),
        base_url=str(request.base_url).rstrip("/"),
    )


@router.get("/sessions/{session_id}/results")
def get_session_results(
    request: Request,
    session_id: str,
    _: bool = Depends(require_musa_api_key),
):
    """
    Get full analytics results for a completed session.

    Returns SessionResponse with pdf_url when complete.
    """
    try:
        supabase = get_supabase()
        session_result = (
            supabase.table("musa_sessions")
            .select("*")
            .eq("session_id", session_id)
            .execute()
        )
    except Exception:
        logger.exception("Failed to query musa_session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve session")

    rows = session_result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Session not found")

    session = rows[0]

    # Allow both "complete" and "failed" - both are finished processing
    if session["status"] == "processing":
        raise HTTPException(status_code=400, detail="Session still processing")

    deal_id = session.get("deal_id")

    # Return the SessionResponse (works for both complete and failed)
    return _build_session_response(
        session,
        deal_id,
        base_url=str(request.base_url).rstrip("/"),
    )
