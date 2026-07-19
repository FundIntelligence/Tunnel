"""
I&M Bank (Kenya) PDF statement extractor.

Columns: Transaction date | Value date | Description/Narration |
         Transaction reference | Withdrawal | Deposit | Balance
Date: DD-Mon-YYYY (e.g. "02-Mar-2026") → ISO
Description/Narration often wraps onto several lines under the dated row
(e.g. "MMP/Mpesa 391572" / "Ref UC29L89BYW" / "From PETRO OWINO O") — these
continuation lines carry no date and are appended to the pending row's
description, same pattern as the ABSA extractor.

The bank's name renders as a logo image only — it never appears in
extract_text() and there's no identifying PDF metadata (Producer is just
generic iText). Detection instead fingerprints the unique column header
combination "Description/Narration" + "Transaction reference", confirmed
unique against every other supported bank's header text.

Uses extract_words + x-thresholds (no ruled table lines in this PDF, so
extract_tables() returns nothing — same situation as ABSA).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Tuple, Union

import pdfplumber

from app.models import ExtractionResult, RawTransaction, WarningItem
from app.extractors.shared import _group_by_line
from app.extractors.pdf_document import NormalizedDocument, as_document

# X-thresholds derived from real I&M Bank statement word positions.
_DATE1_X_MAX = 130.0   # Transaction date
_DATE2_X_MAX = 250.0   # Value date
_DESC_X_MAX = 365.0    # Description/Narration
_REF_X_MAX = 480.0     # Transaction reference (discarded — not needed downstream)
_WITHDRAWAL_X_MAX = 590.0
_DEPOSIT_X_MAX = 705.0
# Balance: x0 >= 705
_AMOUNT_PAT = re.compile(r"^[\d,]+\.\d{2}$")
_DATE_PAT = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{4}$")
_ROW_TOLERANCE = 5.0


def detect_im(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF appears to be an I&M Bank statement."""
    try:
        with as_document(source) as doc:
            text = doc.text_upto(2)
            return "Description/Narration" in text and "Transaction reference" in text
    except Exception:
        return False


def _parse_im_date(raw: str) -> Optional[str]:
    """Parse DD-Mon-YYYY (e.g. 02-Mar-2026) to ISO YYYY-MM-DD."""
    if not raw or not raw.strip():
        return None
    try:
        dt = datetime.strptime(raw.strip(), "%d-%b-%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _try_parse_balance(raw: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Try to parse balance string to cents. Returns (cents, warning).
    Helper in extractor only — does not duplicate normaliser._parse_cents.
    """
    if not raw or raw.strip() in ("", "nan"):
        return None, None

    clean = raw.replace(",", "").strip()
    if clean.startswith("-"):
        clean = clean[1:]
    elif clean.startswith("+"):
        clean = clean[1:]
    if not clean:
        return None, f"empty balance: {raw!r}"

    try:
        if "." in clean:
            whole_str, frac_str = clean.split(".", 1)
            frac_str = frac_str.ljust(2, "0")[:2]
            whole = int(whole_str) if whole_str else 0
            frac = int(frac_str)
            return whole * 100 + frac, None
        return int(clean) * 100, None
    except ValueError:
        return None, f"malformed balance: {raw!r}"


def _is_header_row(date1_parts: List[str], desc_parts: List[str]) -> bool:
    date_str = " ".join(date1_parts).upper()
    desc_str = " ".join(desc_parts).upper()
    return (
        "TRANSACTION" in date_str
        or "DATE" in date_str
        or "DESCRIPTION" in desc_str
        or "NARRATION" in desc_str
    )


def _is_footer_or_marketing(text: str) -> bool:
    t = (text or "").upper()
    return (
        ("PAGE" in t and "OF" in t)
        or "STATEMENT PERIOD" in t
        or "ACCOUNT CURRENCY" in t
        or "TRANSACTIONS HISTORY" in t
    )


def _assign_word_column(w: dict) -> Optional[str]:
    text = w.get("text", "")
    x0 = w.get("x0", 0)
    if _AMOUNT_PAT.match(text):
        if x0 >= _DEPOSIT_X_MAX:
            return "balance"
        if x0 >= _WITHDRAWAL_X_MAX:
            return "deposit"
        if x0 >= _REF_X_MAX:
            return "withdrawal"
    if x0 < _DATE1_X_MAX:
        return "date1"
    if x0 < _DATE2_X_MAX:
        return "date2"
    if x0 < _DESC_X_MAX:
        return "desc"
    if x0 < _REF_X_MAX:
        return "ref"  # discarded — transaction reference, not needed downstream
    return None


def _flush_im_pending(
    pending: dict,
    transactions: List[RawTransaction],
    warnings: List[WarningItem],
) -> None:
    _, balance_warn = _try_parse_balance(pending.get("balance_raw", ""))
    if balance_warn:
        warnings.append(
            WarningItem(
                row_index=pending["row_index"],
                message=balance_warn,
                raw_text=pending.get("balance_raw", ""),
            )
        )

    transactions.append(
        RawTransaction(
            row_index=pending["row_index"],
            date_raw=pending["date_raw"],
            description=pending["description"] or "",
            debit_raw=pending["debit_raw"],
            credit_raw=pending["credit_raw"],
            balance_raw=pending["balance_raw"],
            source_file=pending["source_file"],
            extraction_confidence=1.0,
        )
    )


def extract_im_pdf(file_path: str) -> ExtractionResult:
    transactions: List[RawTransaction] = []
    warnings: List[WarningItem] = []
    row_idx = 0

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            if not words:
                continue

            rows = _group_by_line(words, _ROW_TOLERANCE)
            pending: Optional[dict] = None

            for row_words in rows:
                date1_parts: List[str] = []
                desc_parts: List[str] = []
                withdrawal = ""
                deposit = ""
                balance_raw = ""

                for w in row_words:
                    col = _assign_word_column(w)
                    if col == "date1":
                        date1_parts.append(w["text"])
                    elif col == "desc":
                        desc_parts.append(w["text"])
                    elif col == "withdrawal":
                        withdrawal = w["text"]
                    elif col == "deposit":
                        deposit = w["text"]
                    elif col == "balance":
                        balance_raw = w["text"]
                    # col == "date2" / "ref" / None: discarded by design

                date1_str = " ".join(date1_parts).strip()
                desc_str = " ".join(desc_parts).strip()

                if _is_header_row(date1_parts, desc_parts):
                    continue

                if _is_footer_or_marketing(desc_str) or _is_footer_or_marketing(date1_str):
                    continue

                if not date1_str and not desc_str and not withdrawal and not deposit:
                    continue

                # A bare date with nothing else on the line is statement-period
                # boilerplate ("From / 01-Mar-2026"), not a transaction — every
                # real row has at least a description and usually an amount.
                if date1_str and not desc_str and not withdrawal and not deposit and not balance_raw:
                    continue

                iso_date = _parse_im_date(date1_str) or ""

                if date1_str and _DATE_PAT.match(date1_str) and iso_date:
                    if pending:
                        _flush_im_pending(pending, transactions, warnings)
                        pending = None
                    pending = {
                        "row_index": row_idx,
                        "date_raw": iso_date,
                        "description": desc_str,
                        "debit_raw": withdrawal.replace(",", "").lstrip("-") if withdrawal else "",
                        "credit_raw": deposit.replace(",", "") if deposit else "",
                        "balance_raw": balance_raw,
                        "source_file": file_path,
                    }
                    row_idx += 1
                else:
                    if pending:
                        if desc_str:
                            pending["description"] = (
                                (pending["description"] or "") + " " + desc_str
                            ).strip()
                        if withdrawal and not pending["debit_raw"]:
                            pending["debit_raw"] = withdrawal.replace(",", "").lstrip("-")
                        if deposit and not pending["credit_raw"]:
                            pending["credit_raw"] = deposit.replace(",", "")
                        if balance_raw and not pending["balance_raw"]:
                            pending["balance_raw"] = balance_raw

            if pending:
                _flush_im_pending(pending, transactions, warnings)
                pending = None

    has_warnings = len(warnings) > 0
    return ExtractionResult(
        source_file=file_path,
        extractor_type="im_pdf",
        row_count=len(transactions),
        extraction_status="needs_review" if has_warnings else "success",
        warnings=warnings,
        raw_transactions=transactions,
    )
