"""
ABSA Bank Kenya PDF statement extractor.

Columns: Txn Date | Description | User Narrative | Money Out | Money In | Balance
Date: DD/MM/YYYY → ISO
User Narrative: append as description + " | " + user_narrative. If blank, use description only.
Money Out → negative (debit_raw). Money In → positive (credit_raw).

Some Absa templates (e.g. "Corporate and Business Banking" statements)
insert a second Value Date column immediately after Txn Date, still inside
the x0 < _TXN_DATE_X_MAX zone. Without handling it, both dates concatenate
into one unparseable string ("29/05/2026 31/05/2026"), every row silently
fails date parsing, and the whole file extracts zero transactions. Guarded
below by only ever keeping the first date-shaped token per row — the
common-case single-date template only ever has one, so this is a no-op
for it.

Uses extract_words + x-thresholds (no tables in ABSA PDF).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Tuple, Union

import pdfplumber

from app.models import ExtractionResult, RawTransaction, WarningItem
from app.extractors.shared import _group_by_line
from app.extractors.pdf_document import NormalizedDocument, as_document

# X-thresholds from real file (words)
_TXN_DATE_X_MAX = 120.0
_DESC_X_MAX = 400.0
_MONEY_OUT_X_MAX = 465.0
_MONEY_IN_X_MAX = 515.0
# Balance: x0 >= 515
_AMOUNT_PAT = re.compile(r"^[\d,]+\.\d{2}$")
_DATE_TOKEN_PAT = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_ROW_TOLERANCE = 5.0


def detect_absa(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF appears to be an ABSA Bank Kenya statement."""
    try:
        with as_document(source) as doc:
            text = doc.text_upto(3)
            return (
                "Absa Bank Kenya" in text
                or "absa.kenya@absa.africa" in text
            )
    except Exception:
        return False


def _parse_absa_date(raw: str) -> Optional[str]:
    """Parse DD/MM/YYYY to ISO YYYY-MM-DD."""
    if not raw or not raw.strip():
        return None
    try:
        dt = datetime.strptime(raw.strip(), "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _try_parse_balance(raw: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Try to parse balance string to cents. Returns (cents, warning).
    If parse fails, returns (None, warning_message).
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


def _is_header_row(date_parts: List[str], desc_parts: List[str]) -> bool:
    date_str = " ".join(date_parts).upper()
    desc_str = " ".join(desc_parts).upper()
    return "TXN DATE" in date_str or "DATE" in date_str or "DESCRIPTION" in desc_str


def _flush_absa_pending(
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


def _is_footer_or_marketing(text: str) -> bool:
    t = (text or "").upper()
    return (
        "PAGE" in t and "OF" in t
        or "CONTINUED" in t
        or "MARKETING" in t
        or "absa.kenya@absa.africa" in t
        or "KEEP THIS STATEMENT" in t
    )


def _assign_word_column(w: dict) -> Optional[str]:
    text = w.get("text", "")
    x0 = w.get("x0", 0)
    if _AMOUNT_PAT.match(text):
        if x0 >= _MONEY_IN_X_MAX:
            return "balance"
        if x0 >= _MONEY_OUT_X_MAX:
            return "money_in"
        if x0 >= _DESC_X_MAX:
            return "money_out"
    if x0 < _TXN_DATE_X_MAX:
        return "date"
    if x0 < _DESC_X_MAX:
        return "desc"
    return None


def extract_absa_pdf(file_path: str) -> ExtractionResult:
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
                date_parts: List[str] = []
                desc_parts: List[str] = []
                money_out = ""
                money_in = ""
                balance_raw = ""

                for w in row_words:
                    col = _assign_word_column(w)
                    if col == "date":
                        if date_parts and _DATE_TOKEN_PAT.match(w["text"]):
                            continue  # value date column — transaction date already captured
                        date_parts.append(w["text"])
                    elif col == "desc":
                        desc_parts.append(w["text"])
                    elif col == "money_out":
                        money_out = w["text"]
                    elif col == "money_in":
                        money_in = w["text"]
                    elif col == "balance":
                        balance_raw = w["text"]

                date_str = " ".join(date_parts).strip()
                desc_str = " ".join(desc_parts).strip()

                if _is_header_row(date_parts, desc_parts):
                    continue

                if _is_footer_or_marketing(desc_str):
                    continue

                if not date_str and not desc_str and not money_out and not money_in:
                    continue

                # End-of-statement "Total <money out> <money in>" recap row: no
                # date, no description, both amount columns populated at once.
                # A real transaction never has both a debit and a credit value
                # on the same row, so this combination is a safe, specific
                # signature — without it, this synthetic row's amounts merge
                # into whichever transaction is still pending (no date of its
                # own to start a new one), corrupting that real transaction's
                # debit/credit.
                if not date_str and not desc_str and money_out and money_in:
                    continue

                iso_date = _parse_absa_date(date_str) or ""

                if date_str and _parse_absa_date(date_str):
                    if pending:
                        _flush_absa_pending(pending, transactions, warnings)
                        pending = None
                    pending = {
                        "row_index": row_idx,
                        "date_raw": iso_date,
                        "description": desc_str,
                        "debit_raw": money_out.replace(",", "").lstrip("-") if money_out else "",
                        "credit_raw": money_in.replace(",", "") if money_in else "",
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
                        if money_out and not pending["debit_raw"]:
                            pending["debit_raw"] = money_out.replace(",", "").lstrip("-")
                        if money_in and not pending["credit_raw"]:
                            pending["credit_raw"] = money_in.replace(",", "")
                        if balance_raw and not pending["balance_raw"]:
                            pending["balance_raw"] = balance_raw

            if pending:
                _flush_absa_pending(pending, transactions, warnings)
                pending = None

    has_warnings = len(warnings) > 0
    return ExtractionResult(
        source_file=file_path,
        extractor_type="absa_pdf",
        row_count=len(transactions),
        extraction_status="needs_review" if has_warnings else "success",
        warnings=warnings,
        raw_transactions=transactions,
    )
