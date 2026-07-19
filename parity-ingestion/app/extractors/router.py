"""
Bank format detection and extraction router.

XLSX is routed by extension first. PDF detection order:
KCB → KCB_Online → Equity_CLMS → NCBA → Equity → ABSA → COOP → MPESA_PDF → Stanbic → I&M → SCB

Note: Equity_CLMS must precede NCBA because some CLMS statements trigger NCBA detection.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

from app.extractors.kcb_extractor import detect_kcb, extract_kcb_pdf, detect_kcb_online, extract_kcb_online_pdf
from app.extractors.ncba_extractor import detect_ncba, extract_ncba_pdf
from app.extractors.equity_extractor import detect_equity, extract_equity_pdf, detect_equity_clms, extract_equity_clms_pdf
from app.extractors.absa_extractor import detect_absa, extract_absa_pdf
from app.extractors.coop_extractor import detect_coop, extract_coop_pdf
from app.extractors.mpesa_pdf_extractor import detect_mpesa_pdf, extract_mpesa_pdf
from app.extractors.stanbic_extractor import detect_stanbic, extract_stanbic_pdf
from app.extractors.im_extractor import detect_im, extract_im_pdf
from app.extractors.pdf_extractor import extract_scb_pdf
from app.extractors.currency_detector import detect as detect_currency
from app.extractors.pdf_document import NormalizedDocument, parse_pdf

from app.models import ExtractionResult

logger = logging.getLogger(__name__)

UNSUPPORTED_RESPONSE = {
    "status": "UNSUPPORTED_FORMAT",
    "message": (
        "Bank format not recognised. Supported formats: SCB, Co-op, ABSA, M-Pesa, "
        "Equity Bank, KCB, NCBA, Stanbic, I&M Bank"
    ),
}


def _pre_extract_currency(doc: NormalizedDocument) -> Optional[str]:
    """
    Run L1 currency detection against the first 2 pages of an
    already-parsed document. Returns ISO 4217 code or None. Never raises.
    Used as a pre-routing belt-and-braces check; individual extractors
    retain their own detection as the primary signal.
    """
    try:
        return detect_currency(doc.text_upto(2))
    except Exception:
        return None


def route_extract(file_path: str) -> Union[ExtractionResult, dict]:
    """
    Detect bank format and run the appropriate extractor.
    Returns ExtractionResult on success, or UNSUPPORTED_RESPONSE dict if no format matches.

    PDF detection (currency pre-extraction + all 10 bank-format detectors)
    shares a single parse of the file (PAR-36) — previously each detector and
    the currency pre-check opened the file independently via its own
    `pdfplumber.open()` call (confirmed up to 11 opens for one document).
    The winning extractor below still does its own open for now — threading
    the shared parse all the way into each bank-specific extractor's
    column/table logic is scoped to a follow-up (see PAR-37, which needs this
    same single-parse contract to swap the word-extraction engine).
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".xlsx":
        from app.extractors.xlsx_extractor import extract_xlsx

        return extract_xlsx(file_path)

    try:
        with parse_pdf(file_path) as doc:
            # Pre-extraction: L1 currency detection from first 2 pages.
            # Result is logged for observability; individual parsers use their own detection.
            currency_hint = _pre_extract_currency(doc)
            if currency_hint:
                logger.debug("Router pre-detected currency=%s for %s", currency_hint, file_path)

            if detect_kcb(doc):
                return extract_kcb_pdf(file_path)
            if detect_kcb_online(doc):
                return extract_kcb_online_pdf(file_path)
            if detect_equity_clms(doc):
                return extract_equity_clms_pdf(file_path)
            if detect_ncba(doc):
                return extract_ncba_pdf(file_path)
            if detect_equity(doc):
                return extract_equity_pdf(file_path)
            if detect_absa(doc):
                return extract_absa_pdf(file_path)
            if detect_coop(doc):
                return extract_coop_pdf(file_path)
            if detect_mpesa_pdf(doc):
                return extract_mpesa_pdf(file_path)
            if detect_stanbic(doc):
                return extract_stanbic_pdf(file_path)
            if detect_im(doc):
                return extract_im_pdf(file_path)

            if doc.pages:
                text = doc.pages[0].text
                if "Particulars" in text and "Statement Of Account" in text:
                    return extract_scb_pdf(file_path)
    except Exception:
        # A file that isn't a valid PDF at all (unopenable/corrupt) previously
        # fell through to UNSUPPORTED_RESPONSE because every detector opened
        # the file independently and caught its own exception. The single
        # shared parse below must preserve that: an unopenable file is
        # "unsupported", not a 500.
        logger.debug("route_extract: failed to parse %s as PDF", file_path, exc_info=True)
        return UNSUPPORTED_RESPONSE

    return UNSUPPORTED_RESPONSE
