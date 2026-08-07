from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel


# ── Phase 1 models ──────────────────────────────────────────────────────────

ExtractionMethod = Literal[
    "scb_pdf",
    "mpesa_csv",
    "document_ai",
    "coop_pdf",
    "absa_pdf",
    "mpesa_pdf",
    "equity_pdf",
    "kcb_pdf",
    "kcb_online_pdf",
    "ncba_pdf",
    "ncba_estatement_pdf",
    "stanbic_pdf",
    "im_pdf",
    "equity_xlsx",
    "xlsx_generic",
]


class DocType(str, Enum):
    DIGITAL_PDF = "digital_pdf"
    SCANNED_PDF = "scanned_pdf"


class WarningItem(BaseModel):
    row_index: int
    message: str
    raw_text: str


class RawTransaction(BaseModel):
    row_index: int
    date_raw: str        # stored exactly as extracted — no parsing
    description: str
    debit_raw: str       # raw string, e.g. "320,000.00" or ""
    credit_raw: str      # raw string, e.g. "371,200.00" or ""
    balance_raw: str     # raw string, e.g. "1,733,938.24" or ""
    source_file: str
    extraction_confidence: float = 1.0  # 1.0 = all fields present; <1.0 = partial row
    source_extraction_method: Optional[str] = None
    balance_is_overdrawn: Optional[bool] = None
    classification_status: str = "AUTO_CLASSIFIED"
    pattern_hint: str = ""


# ── Phase 3 models ──────────────────────────────────────────────────────────

class NormalisationStatus(str, Enum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"


class NormalisedTransaction(BaseModel):
    # Identity
    row_index: int
    source_extraction_method: ExtractionMethod
    page_number: Optional[int] = None
    receipt_no: Optional[str] = None        # M-Pesa only (Phase 4+)

    # Normalised fields
    date: Optional[str] = None              # ISO 8601: YYYY-MM-DD
    description: str = ""
    debit_cents: Optional[int] = None       # integer cents, always positive
    credit_cents: Optional[int] = None      # integer cents, always positive
    balance_cents: Optional[int] = None     # integer cents (may be signed)
    currency: str = "KES"

    # Provenance — original strings preserved for audit
    raw_date: Optional[str] = None
    raw_debit: Optional[str] = None
    raw_credit: Optional[str] = None
    raw_balance: Optional[str] = None

    # Quality
    row_confidence: float = 1.0
    normalisation_status: NormalisationStatus = NormalisationStatus.OK
    normalisation_warnings: List[str] = []


# ── Shared result model ──────────────────────────────────────────────────────

class ExtractionResult(BaseModel):
    source_file: str
    extractor_type: ExtractionMethod
    row_count: int
    extraction_status: Literal["success", "needs_review", "failed"]
    warnings: List[WarningItem]
    raw_transactions: List[RawTransaction]
    # Phase 3 additions
    normalised_transactions: List[NormalisedTransaction] = []
    normalisation_warnings: List[str] = []
    result_id: Optional[str] = None
    # Phase 2 additions
    doc_type: Optional[DocType] = None
    # Currency — ISO 4217 code detected from statement header
    currency: str = "KES"
