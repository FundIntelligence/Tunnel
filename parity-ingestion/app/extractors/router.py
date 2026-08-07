"""
Bank format detection and extraction router.

XLSX is routed by extension first. PDF detection order:
KCB → KCB_Online → Equity_CLMS → Equity_F1 → NCBA → Equity → ABSA → COOP → MPESA_PDF → Stanbic → I&M → SCB

Note: Equity_CLMS must precede NCBA because some CLMS statements trigger NCBA detection.
Equity_F1 must precede the generic Equity check since it's structurally a
distinct layout (Tran Particulars/Instrument columns, no "Running Balance").
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

from app.extractors.kcb_extractor import detect_kcb, extract_kcb_pdf, detect_kcb_online, extract_kcb_online_pdf
from app.extractors.ncba_extractor import detect_ncba, extract_ncba_pdf, detect_ncba_estatement, extract_ncba_estatement_pdf
from app.extractors.equity_extractor import detect_equity, extract_equity_pdf, detect_equity_clms, extract_equity_clms_pdf, detect_equity_f1, extract_equity_f1_pdf
from app.extractors.absa_extractor import detect_absa, extract_absa_pdf
from app.extractors.coop_extractor import detect_coop, extract_coop_pdf
from app.extractors.mpesa_pdf_extractor import detect_mpesa_pdf, extract_mpesa_pdf
from app.extractors.stanbic_extractor import detect_stanbic, extract_stanbic_pdf
from app.extractors.im_extractor import detect_im, extract_im_pdf
from app.extractors.pdf_extractor import extract_scb_pdf
from app.extractors.currency_detector import detect as detect_currency
from app.extractors.pdf_document import NormalizedDocument, parse_pdf, PDFLockedError

from app.models import ExtractionResult

logger = logging.getLogger(__name__)

UNSUPPORTED_RESPONSE = {
    "status": "UNSUPPORTED_FORMAT",
    "message": (
        "Bank format not recognised. Supported formats: SCB, Co-op, ABSA, M-Pesa, "
        "Equity Bank, KCB, NCBA, Stanbic, I&M Bank"
    ),
}

# PAR-69: generic, bank-agnostic password signals — returned before any bank
# detector runs, since a locked PDF can't be format-detected at all yet.
# Distinguished only by whether a password was supplied, so the caller can
# show "this file needs a password" vs. "that password didn't work".
PASSWORD_REQUIRED_RESPONSE = {
    "status": "PASSWORD_REQUIRED",
    "message": "This PDF is password-protected. Provide a password to continue.",
}
PASSWORD_INCORRECT_RESPONSE = {
    "status": "PASSWORD_INCORRECT",
    "message": "The password provided did not unlock this PDF. Please check and try again.",
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


def route_extract(file_path: str, password: Optional[str] = None) -> Union[ExtractionResult, dict]:
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

    `password` (PAR-69): a single, generic, bank-agnostic unlock step, not a
    per-bank one. If the file is encrypted, `parse_pdf()` raises
    `PDFLockedError` before any bank detector runs — at that point the
    router has no idea which bank the file is from, so there's nothing
    bank-specific to do yet. `password` is used in-memory for this call
    only: never written to a DB, config, log, or session — a later call for
    the same file must supply it again. NCBA's "e-Statement Of Account"
    template is the first caller of this path; any future locked-PDF format
    (e.g. PAR-14's Co-op Layout C) reuses the exact same mechanism instead
    of reimplementing password detection per bank.
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".xlsx":
        from app.extractors.xlsx_extractor import extract_xlsx

        return extract_xlsx(file_path)

    try:
        doc = parse_pdf(file_path, password=password)
    except PDFLockedError:
        return PASSWORD_INCORRECT_RESPONSE if password else PASSWORD_REQUIRED_RESPONSE
    except Exception:
        # A file that isn't a valid PDF at all (unopenable/corrupt) previously
        # fell through to UNSUPPORTED_RESPONSE because every detector opened
        # the file independently and caught its own exception. The single
        # shared parse below must preserve that: an unopenable file is
        # "unsupported", not a 500.
        logger.debug("route_extract: failed to parse %s as PDF", file_path, exc_info=True)
        return UNSUPPORTED_RESPONSE

    try:
        with doc:
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
            if detect_equity_f1(doc):
                return extract_equity_f1_pdf(file_path)
            if detect_ncba_estatement(file_path, password=password):
                return extract_ncba_estatement_pdf(file_path, password=password)
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
        logger.debug("route_extract: failed to parse %s as PDF", file_path, exc_info=True)
        return UNSUPPORTED_RESPONSE

    return UNSUPPORTED_RESPONSE
