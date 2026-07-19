"""
Stanbic Bank Kenya PDF statement extractor.

Stanbic PDFs use a CID-encoded font that renders as garbage in pdfplumber,
so all pages are rasterised via pdf2image and OCR'd with pytesseract.
Word bounding-boxes from image_to_data() are then processed with the same
x-threshold + _group_by_line pattern used by the KCB extractor.

Column layout (left → right):
  Transaction Date | Description | Value Date | Debit | Credit | Ledger Balance | Available Balance

Date format:  DD MMM YY  (e.g. "23 AUG 23") → ISO YYYY-MM-DD
Balance:      X,XXX.XXCR  (CR suffix = normal positive balance; no suffix = overdrawn)
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import List, Optional, Union

import pdfplumber

from app.extractors.pdf_document import NormalizedDocument, as_document

# OCR dependencies — optional.  Not available on all deployments (e.g. Render
# workers that lack poppler/tesseract).  When absent, detect_stanbic() returns
# False and Stanbic statements fall through to UNSUPPORTED_FORMAT.
try:
    from pdf2image import convert_from_path as _convert_from_path
    import pytesseract as _pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False
    _convert_from_path = None  # type: ignore[assignment]
    _pytesseract = None  # type: ignore[assignment]

from app.models import ExtractionResult, RawTransaction, WarningItem

# ── OCR resolution ────────────────────────────────────────────────────────────
_OCR_DPI = 300

# ── Column x-boundaries as fractions of image width ──────────────────────────
# Calibrated on a 150 DPI render (1240 × 1755 px).  Fractions are DPI-agnostic.
#
#   Date        |  Desc       |  Value Date  |  Debit  |  Credit  |  Ledger Bal  |  Avail Bal
#   xf < 0.14   | 0.15–0.32  |  0.32–0.44   | 0.44–0.53| 0.53–0.67|  0.67–0.82   |  ≥ 0.82
_DATE_X_MAX_FRAC       = 0.14
_DESC_X_START_FRAC     = 0.15
_DESC_X_END_FRAC       = 0.31   # value-date day digit sits at xf≈0.319; keep it out of desc
# Value Date zone (0.32–0.44) is parsed but discarded.
_DEBIT_X_START_FRAC    = 0.44
_DEBIT_X_END_FRAC      = 0.53
_CREDIT_X_START_FRAC   = 0.53
_CREDIT_X_END_FRAC     = 0.67
_BALANCE_X_START_FRAC  = 0.67
_BALANCE_X_END_FRAC    = 0.82
# Available Balance (xf ≥ 0.82) mirrors Ledger Balance — ignored.

# ── Y-filter: skip document header ───────────────────────────────────────────
# The top ~24 % of each page is the company header + column header row.
# Transaction rows always start below y/H ≈ 0.25.
_HEADER_Y_FRAC = 0.24

# ── Row grouping tolerance (fraction of page height) ─────────────────────────
# Scales with DPI so the same fraction covers one text line at any resolution.
_Y_BUCKET_FRAC = 0.0046   # ~8 px at 150 DPI, ~16 px at 300 DPI

# ── Date patterns ─────────────────────────────────────────────────────────────
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_MONTHS_ALT = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
_DATE_PAT = re.compile(
    r"^(\d{1,2})\s+(" + _MONTHS_ALT + r")\s+(\d{2})$",
    re.IGNORECASE,
)

# ── Amount patterns ───────────────────────────────────────────────────────────
# Full amount (may carry CR suffix from balance column).
_AMOUNT_PAT = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}(?:CR)?$", re.IGNORECASE)
# Fragment: a number ending with a comma that OCR split from the rest of the amount.
_FRAG_PAT   = re.compile(r"^\d{1,3}(?:,\d{3})*,$")
# Any token that begins with a digit (used to capture amount column words).
_NUMERIC_START = re.compile(r"^\d")

# ── Lines to skip (header / footer phrases) ───────────────────────────────────
_SKIP_FRAGS = (
    "ZURIDI AFRICA",        # company name in header
    "P.O BOX",
    "NAIROBI",
    "Customer No",
    "Account No",
    "Acct.",
    "Currency",
    "Statement No",
    "Statement Period",
    "Statement Date",
    "Dear Esteemed Customer",
    "We wish to advise",
    "Thank you for choosing",
    "Please visit",
    "E-Courier",
    "+254",
    "OOCR",                 # OCR artefact from Stanbic's repeat-column layout
    "Transaction Description",
    "Ledger Balance",
    "Available Balance",
    "Value Date",
)


# ── Public API ────────────────────────────────────────────────────────────────

def detect_stanbic(source: Union[str, NormalizedDocument]) -> bool:
    """
    Return True if the PDF is a Stanbic Bank Kenya statement.

    Two-step: first check for CID-encoded font garbage (fast), then OCR the
    first page at 100 DPI to confirm "STANBIC" appears in the text.
    Returns False immediately when OCR dependencies are not installed.
    """
    if not _OCR_AVAILABLE:
        return False
    try:
        with as_document(source) as doc:
            if not doc.pages:
                return False
            text = doc.pages[0].text
            if text.count("(cid:") < 20:
                return False
            file_path = doc.file_path
        # Image conversion (pdf2image/poppler) is unrelated to pdfplumber's
        # parse — always needs the file path directly, regardless of
        # whether we were handed a pre-parsed document.
        images = _convert_from_path(file_path, dpi=100, first_page=1, last_page=1)
        if not images:
            return False
        ocr_text = _pytesseract.image_to_string(images[0], lang="eng")
        return "STANBIC" in ocr_text.upper()
    except Exception:
        return False


def extract_stanbic_pdf(file_path: str) -> ExtractionResult:
    """
    Extract transactions from a Stanbic Bank Kenya PDF via OCR.

    Returns ExtractionResult with raw_transactions as strings (no floats),
    conforming to the Parity Phase-1 extraction contract.
    Currency (KES/USD/EUR/GBP) is auto-detected from the first-page header.
    """
    transactions: List[RawTransaction] = []
    warnings: List[WarningItem] = []
    row_idx = 0
    detected_currency = "KES"  # updated from page-1 header words

    images = _convert_from_path(file_path, dpi=_OCR_DPI)

    for page_num, img in enumerate(images, start=1):
        W, H = img.size
        y_tol = H * _Y_BUCKET_FRAC

        data = _pytesseract.image_to_data(
            img, lang="eng", output_type=_pytesseract.Output.DICT
        )
        all_words = _ocr_words_from_data(data)

        # On the first page, read the header zone to detect currency.
        # Header words are already filtered OUT of transaction parsing, so
        # this is zero extra OCR work.
        if page_num == 1:
            header_words = [w for w in all_words if w["top"] / H <= _HEADER_Y_FRAC]
            header_text  = " ".join(w["text"] for w in header_words)
            detected_currency = _detect_currency_from_ocr(header_text)

        # Strip header area (top _HEADER_Y_FRAC of page).
        words = [w for w in all_words if w["top"] / H > _HEADER_Y_FRAC]
        if not words:
            continue

        rows = _group_by_line(words, y_tol)
        pending: Optional[dict] = None
        in_footer = False

        for row_words in rows:
            if in_footer:
                break

            # Reconstruct line text for skip-phrase detection.
            row_text = " ".join(w["text"] for w in row_words)

            if "Dear Esteemed Customer" in row_text:
                in_footer = True
                break

            if _should_skip_line(row_text):
                continue

            # ── Assign words to columns ───────────────────────────────────
            date_parts:    List[str] = []
            desc_parts:    List[str] = []
            debit_parts:   List[str] = []
            credit_parts:  List[str] = []
            balance_parts: List[str] = []

            for w in row_words:
                col = _assign_col(w, W)
                if col == "date":
                    date_parts.append(w["text"])
                elif col == "desc":
                    desc_parts.append(w["text"])
                elif col == "debit":
                    debit_parts.append(w["text"])
                elif col == "credit":
                    credit_parts.append(w["text"])
                elif col == "balance":
                    balance_parts.append(w["text"])

            date_str    = " ".join(date_parts).strip()
            desc_str    = " ".join(desc_parts).strip()
            debit_raw   = _join_amount_parts(debit_parts)
            credit_raw  = _join_amount_parts(credit_parts)
            balance_raw = _join_amount_parts(balance_parts)

            # Skip truly empty rows.
            if not date_str and not desc_str and not debit_raw and not credit_raw and not balance_raw:
                continue

            # ── BALANCE BROUGHT FORWARD (no date on this row) ────────────
            if not date_str and "BALANCE BROUGHT FORWARD" in desc_str.upper():
                if pending:
                    _flush_pending(pending, transactions)
                    pending = None
                transactions.append(RawTransaction(
                    row_index=row_idx,
                    date_raw="",
                    description="BALANCE BROUGHT FORWARD",
                    debit_raw="",
                    credit_raw="",
                    balance_raw=balance_raw,
                    source_file=file_path,
                    extraction_confidence=0.9,
                ))
                row_idx += 1
                continue

            # ── New transaction (date present) ────────────────────────────
            iso_date = _parse_date(date_str)
            if iso_date is not None:
                if pending:
                    _flush_pending(pending, transactions)
                pending = {
                    "row_index":   row_idx,
                    "date_raw":    iso_date,
                    "description": desc_str,
                    "debit_raw":   debit_raw,
                    "credit_raw":  credit_raw,
                    "balance_raw": balance_raw,
                    "source_file": file_path,
                }
                row_idx += 1

            # ── Continuation / description-only row ───────────────────────
            elif pending:
                if desc_str:
                    pending["description"] = (
                        (pending["description"] + " " + desc_str).strip()
                    )
                if debit_raw and not pending["debit_raw"]:
                    pending["debit_raw"] = debit_raw
                if credit_raw and not pending["credit_raw"]:
                    pending["credit_raw"] = credit_raw
                if balance_raw and not pending["balance_raw"]:
                    pending["balance_raw"] = balance_raw

        # Flush at end of page.
        if pending:
            _flush_pending(pending, transactions)
            pending = None

    return ExtractionResult(
        source_file=file_path,
        extractor_type="stanbic_pdf",
        row_count=len(transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=transactions,
        currency=detected_currency,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

_KNOWN_CURRENCIES = {"USD", "KES", "EUR", "GBP"}
_CURRENCY_PAT = re.compile(r"CURRENCY\s+(\w+)", re.IGNORECASE)


def _detect_currency_from_ocr(text: str) -> str:
    """
    Extract the ISO 4217 currency code from Stanbic header text.

    The header carries a "Currency XXX" label row; e.g.:
      "Currency KES"  or  "Currency USD"

    Falls back to scanning for bare USD/EUR/GBP tokens; defaults to KES
    (the most common Stanbic Kenya denomination).
    """
    m = _CURRENCY_PAT.search(text)
    if m:
        code = m.group(1).upper()
        if code in _KNOWN_CURRENCIES:
            return code
    text_upper = text.upper()
    for code in ("USD", "EUR", "GBP"):
        if code in text_upper:
            return code
    return "KES"


def _ocr_words_from_data(data: dict) -> List[dict]:
    """Convert pytesseract image_to_data output to a list of word dicts."""
    words = []
    for i in range(len(data["text"])):
        txt = data["text"][i].strip()
        conf = int(data["conf"][i])
        if not txt or conf <= 0:
            continue
        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        words.append({"text": txt, "x0": x, "x1": x + w, "top": y})
    return words


def _group_by_line(words: List[dict], y_tol: float) -> List[List[dict]]:
    """
    Bucket words into visual rows by y-position proximity, then sort each
    bucket left-to-right.  Mirrors shared._group_by_line for pdfplumber words.
    """
    if not words:
        return []
    buckets: dict[float, List[dict]] = defaultdict(list)
    for w in words:
        key = round(w["top"] / y_tol) * y_tol
        buckets[key].append(w)
    return [
        sorted(ws, key=lambda w: w["x0"])
        for _, ws in sorted(buckets.items())
    ]


def _assign_col(w: dict, img_width: int) -> Optional[str]:
    """Map a word to its logical column using x-fraction thresholds."""
    xf   = w["x0"] / img_width
    text = w["text"]

    if xf < _DATE_X_MAX_FRAC:
        return "date"
    if _DESC_X_START_FRAC <= xf < _DESC_X_END_FRAC:
        return "desc"
    # Value Date zone (0.32–0.44): intentionally ignored.
    if _DEBIT_X_START_FRAC <= xf < _DEBIT_X_END_FRAC and _NUMERIC_START.match(text):
        return "debit"
    if _CREDIT_X_START_FRAC <= xf < _CREDIT_X_END_FRAC and _NUMERIC_START.match(text):
        return "credit"
    if _BALANCE_X_START_FRAC <= xf < _BALANCE_X_END_FRAC and _NUMERIC_START.match(text):
        return "balance"
    return None


def _join_amount_parts(parts: List[str]) -> str:
    """
    Reconstruct an amount string that OCR may have split at commas.

    Examples:
      ["449,", "458.00CR"]    → "449,458.00CR"
      ["9,509,", "218.00CR"]  → "9,509,218.00CR"
      ["440,000.00"]          → "440,000.00"
      ["250,000."]            → "250,000.00"  (truncated decimal fixed)
    """
    if not parts:
        return ""
    joined = "".join(p.strip() for p in parts).upper()
    # Fix OCR truncation: "250,000." → "250,000.00"
    if joined.endswith("."):
        joined += "00"
    if _AMOUNT_PAT.match(joined):
        return joined
    # If joined is still invalid but the first part alone is valid, use it.
    first = parts[0].strip().upper()
    if _AMOUNT_PAT.match(first):
        return first
    return joined   # Return as-is; the normaliser will flag it.


def _parse_date(s: str) -> Optional[str]:
    """Parse 'DD MON YY' → 'YYYY-MM-DD'.  Returns None if s is not a date."""
    m = _DATE_PAT.match(s.strip())
    if not m:
        return None
    day_s, month_s, year_s = m.groups()
    month = _MONTH_MAP.get(month_s.upper())
    if month is None:
        return None
    year_2d = int(year_s)
    year = 2000 + year_2d if year_2d < 50 else 1900 + year_2d
    return f"{year:04d}-{month:02d}-{int(day_s):02d}"


def _should_skip_line(line_text: str) -> bool:
    """Return True if the line is a known header, footer, or column-label row."""
    for frag in _SKIP_FRAGS:
        if frag in line_text:
            return True
    return False


def _flush_pending(
    pending: dict,
    transactions: List[RawTransaction],
) -> None:
    """Emit a completed pending transaction, zeroing amounts for B/FWD rows."""
    desc = pending.get("description", "")
    if "B/FWD" in desc.upper() or "BALANCE BROUGHT FORWARD" in desc.upper():
        pending["debit_raw"]  = ""
        pending["credit_raw"] = ""

    transactions.append(RawTransaction(
        row_index=pending["row_index"],
        date_raw=pending["date_raw"],
        description=desc,
        debit_raw=pending.get("debit_raw", ""),
        credit_raw=pending.get("credit_raw", ""),
        balance_raw=pending.get("balance_raw", ""),
        source_file=pending["source_file"],
        extraction_confidence=1.0,
    ))
