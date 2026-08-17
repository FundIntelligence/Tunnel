"""
Parity Classify Sandbox — isolated external service (PAR-132).

Wraps the existing deterministic core engine (v1/core/classifier.py) behind
its own auth/metering layer, deliberately kept off api.py's route set so
unproven external sandbox traffic can never degrade the main product
(PAR-132 decision doc). Single endpoint only, per the original sandbox
scoping: POST /v1/classify.
"""
import logging

from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import backend_path  # noqa: F401  (import order matters: sys.path must be patched first)
from .config import bootstrap_sandbox_supabase_env
from .usage import find_active_key_row, increment_usage_or_none
from v1.core.classifier import classify_with_reason
from v1.integrations.auth import require_scoped_api_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_SCOPE = "sandbox-classify"

bootstrap_sandbox_supabase_env()


app = FastAPI(
    title="Parity Classify Sandbox",
    description="Isolated external sandbox: POST /v1/classify only.",
    version="1.0.0",
)


class ClassifyRequest(BaseModel):
    normalized_descriptor: str = Field(..., description="Normalized transaction descriptor")
    signed_amount_cents: int = Field(..., description="Signed amount in integer cents")
    is_transfer: bool = False
    large_positive_threshold_cents: Optional[int] = None
    median_txn_abs_cents: Optional[int] = None


class ClassifyResponse(BaseModel):
    role: str
    classification_reason: str


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    logger.exception("[UNHANDLED] %s", exc)
    return JSONResponse(status_code=500, content={"status": "error", "error_type": type(exc).__name__})


@app.get("/")
async def root():
    return {"service": "Parity Classify Sandbox", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post(
    "/v1/classify",
    response_model=ClassifyResponse,
    dependencies=[Depends(require_scoped_api_key(_SCOPE))],
)
async def classify(payload: ClassifyRequest, x_api_key: str = Header(..., alias="x-api-key")):
    # require_scoped_api_key already proved *some* active sandbox-classify key
    # matches; re-resolve to the specific row so usage can be metered against
    # the right id (see app/usage.py for why this isn't a single lookup).
    key_row = find_active_key_row(x_api_key, _SCOPE)
    if key_row is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    updated = increment_usage_or_none(key_row["id"])
    if updated is None:
        raise HTTPException(status_code=403, detail="API key is revoked or has reached its call cap")

    txn = {
        "normalized_descriptor": payload.normalized_descriptor,
        "signed_amount_cents": payload.signed_amount_cents,
        "is_transfer": payload.is_transfer,
    }
    role, reason = classify_with_reason(
        txn,
        large_positive_threshold_cents=payload.large_positive_threshold_cents,
        median_txn_abs_cents=payload.median_txn_abs_cents,
    )
    return ClassifyResponse(role=role, classification_reason=reason)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
