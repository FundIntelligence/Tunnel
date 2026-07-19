"""
KCB Bank Kenya PDF statement extractor.

Two formats supported:

  1. KCB branch/printed format (kcb_pdf)
     Columns: TXN DATE | DESCRIPTION | VALUE DATE | MONEY OUT | MONEY IN | LEDGER BALANCE
     Date format: DD MON YYYY (e.g. 20 JUL 2023)

  2. KCB Online Banking portal format (kcb_online_pdf)
     Columns: Transaction Date | Value Date | Transaction Details | Money Out | Money In | Ledger Balance | Bank Reference Number
     Date format: DD.MM.YYYY (e.g. 30.01.2025)
     No "KCB" keyword in header; header says "Account Statement"
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Union

import pdfplumber

from app.models import ExtractionResult, RawTransaction, WarningItem
from app.extractors.shared import _group_by_line
from app.extractors.pdf_document import NormalizedDocument, as_document

# X-thresholds from Step 0 (measured from real file)
_TXN_DATE_X_MAX = 95.0
_DESC_X_START = 197.6
_DESC_X_MAX = 340.0
_VALUE_DATE_X_START = 349.95
_VALUE_DATE_X_MAX = 500.0
_MONEY_OUT_X_START = 501.0
_MONEY_OUT_X_MAX = 650.0
_MONEY_IN_X_START = 653.0
_MONEY_IN_X_MAX = 800.0
_BALANCE_X_START = 805.0

_ROW_TOLERANCE = 3.0
_TXN_DATE_PAT = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$")
_AMOUNT_PAT = re.compile(r"^[\d,]+\.\d{2}$")

MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_kcb_date(s: str) -> Optional[str]:
    """Parse '20 JUL 2023' to '2023-07-20'."""
    s = s.strip()
    if not s:
        return None
    parts = s.split()
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        mon = MONTH_MAP.get(parts[1].upper())
        year = int(parts[2])
        if mon is None:
            return None
        return f"{year}-{mon:02d}-{day:02d}"
    except (ValueError, IndexError):
        return None


def detect_kcb(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF appears to be a KCB account statement."""
    try:
        with as_document(source) as doc:
            if not doc.pages:
                return False
            text_upper = doc.pages[0].text.upper()
            has_kcb = "KCB" in text_upper or "KCB BANK" in text_upper
            has_stmt = "ACCOUNT STATEMENT" in text_upper
            has_cols = "TXN DATE" in text_upper and "LEDGER BALANCE" in text_upper
            return bool(has_kcb and has_stmt and has_cols)
    except Exception:
        return False


def derive_missing_debits(transactions: List[RawTransaction]) -> List[RawTransaction]:
    """Derive missing debit/credit from balance movement when MONEY OUT/IN columns are empty."""
    for i in range(1, len(transactions)):
        t = transactions[i]
        prev = transactions[i - 1]
        if t.debit_raw == "" and t.credit_raw == "":
            try:
                prev_bal = float(prev.balance_raw.replace(",", ""))
                curr_bal = float(t.balance_raw.replace(",", ""))
                diff = prev_bal - curr_bal
                if diff > 0:
                    t.debit_raw = str(round(diff, 2))
                elif diff < 0:
                    t.credit_raw = str(round(abs(diff), 2))
            except Exception:
                pass
    return transactions


def _assign_kcb_column(w: dict) -> Optional[str]:
    text = w.get("text", "")
    x0 = w.get("x0", 0)

    if _AMOUNT_PAT.match(text):
        if x0 >= _BALANCE_X_START:
            return "balance"
        if x0 >= _MONEY_IN_X_START:
            return "money_in"
        if x0 >= _MONEY_OUT_X_START:
            return "money_out"

    if x0 < _TXN_DATE_X_MAX:
        return "txn_date"
    if _DESC_X_START <= x0 < _DESC_X_MAX:
        return "desc"
    if _VALUE_DATE_X_START <= x0 < _VALUE_DATE_X_MAX:
        return "value_date"
    return None


def extract_kcb_pdf(file_path: str) -> ExtractionResult:
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
                txn_date_parts: List[str] = []
                desc_parts: List[str] = []
                value_date_parts: List[str] = []
                money_out = ""
                money_in = ""
                balance_raw = ""

                for w in row_words:
                    col = _assign_kcb_column(w)
                    if col == "txn_date":
                        txn_date_parts.append(w["text"])
                    elif col == "desc":
                        desc_parts.append(w["text"])
                    elif col == "value_date":
                        value_date_parts.append(w["text"])
                    elif col == "money_out":
                        money_out = w["text"]
                    elif col == "money_in":
                        money_in = w["text"]
                    elif col == "balance":
                        balance_raw = w["text"]

                txn_date_str = " ".join(txn_date_parts).strip()
                desc_str = " ".join(desc_parts).strip()
                value_date_str = " ".join(value_date_parts).strip()

                if any(phrase in desc_str.upper() for phrase in [
                    "BALANCE AT PERIOD END",
                    "PERIOD END"
                ]):
                    continue

                if not txn_date_str and not desc_str and not money_out and not money_in:
                    continue

                iso_date = parse_kcb_date(txn_date_str)

                if txn_date_str and _TXN_DATE_PAT.match(txn_date_str):
                    if pending:
                        _flush_kcb_pending(pending, transactions, warnings)
                        pending = None

                    pending = {
                        "row_index": row_idx,
                        "date_raw": iso_date or txn_date_str,
                        "description": desc_str,
                        "debit_raw": money_out.replace(",", "").lstrip("-") if money_out else "",
                        "credit_raw": money_in.replace(",", "") if money_in else "",
                        "balance_raw": balance_raw,
                        "source_file": file_path,
                    }
                    row_idx += 1
                else:
                    if pending and desc_str:
                        pending["description"] = (
                            (pending["description"] or "") + " " + desc_str
                        ).strip()
                    if pending and money_out and not pending["debit_raw"]:
                        pending["debit_raw"] = money_out.replace(",", "").lstrip("-")
                    if pending and money_in and not pending["credit_raw"]:
                        pending["credit_raw"] = money_in.replace(",", "")
                    if pending and balance_raw and not pending["balance_raw"]:
                        pending["balance_raw"] = balance_raw

            if pending:
                _flush_kcb_pending(pending, transactions, warnings)
                pending = None

    transactions = derive_missing_debits(transactions)

    return ExtractionResult(
        source_file=file_path,
        extractor_type="kcb_pdf",
        row_count=len(transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=transactions,
    )


# ─────────────────────────────────────────────────────────────────────────────
# KCB Online Banking portal format (DD.MM.YYYY dates)
# ─────────────────────────────────────────────────────────────────────────────

_KCB_ONLINE_DATE_PAT = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_KCB_ONLINE_AMOUNT_PAT = re.compile(r"^-?[\d,]+\.\d{2}$")

# X-thresholds measured from Buildex KCB Online statement
_KCB_ONLINE_TXN_DATE_X_MIN = 45.0
_KCB_ONLINE_TXN_DATE_X_MAX = 120.0
_KCB_ONLINE_DESC_X_MIN = 220.0
_KCB_ONLINE_DESC_X_MAX = 455.0
_KCB_ONLINE_MONEY_OUT_X_MIN = 450.0
_KCB_ONLINE_MONEY_OUT_X_MAX = 548.0
_KCB_ONLINE_MONEY_IN_X_MIN = 548.0
_KCB_ONLINE_MONEY_IN_X_MAX = 648.0
_KCB_ONLINE_BALANCE_X_MIN = 648.0
_KCB_ONLINE_REF_X_MIN = 715.0
_KCB_ONLINE_ROW_TOLERANCE = 3.5
# Max pixels a floating description word may sit ABOVE its anchor row before
# being discarded as a column header or account-summary artifact.
_KCB_ONLINE_DESC_ABOVE_MAX = 22.0


def detect_kcb_online(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF is a KCB Online Banking portal statement.

    This format uses "Account Statement" (not "KCB ACCOUNT STATEMENT") with
    DD.MM.YYYY dates, and "Money In / Money Out / Ledger Balance" column headers.
    """
    try:
        with as_document(source) as doc:
            if not doc.pages:
                return False
            text = doc.pages[0].text
            return (
                "Account Statement" in text
                and "Money In" in text
                and "Money Out" in text
                and "Ledger Balance" in text
                and bool(re.search(r"\d{2}\.\d{2}\.\d{4}", text))
            )
    except Exception:
        return False


def _parse_kcb_online_date(s: str) -> Optional[str]:
    """Parse DD.MM.YYYY to ISO YYYY-MM-DD."""
    try:
        dt = datetime.strptime(s.strip(), "%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _clean_kcb_online_amount(raw: str) -> str:
    """Return amount string suitable for debit_raw / credit_raw (no commas, no minus sign).

    Returns "" when the raw value is zero or empty, so the normaliser treats it as absent.
    """
    if not raw:
        return ""
    cleaned = raw.replace(",", "").lstrip("-").strip()
    if cleaned in ("0.00", "0", ""):
        return ""
    return cleaned


def _kcb_online_anchor_column(w: dict) -> Optional[str]:
    """Classify a word on an anchor row into its column slot."""
    x0 = w["x0"]
    text = w["text"]
    is_amount = bool(_KCB_ONLINE_AMOUNT_PAT.match(text))

    if is_amount:
        if x0 >= _KCB_ONLINE_BALANCE_X_MIN:
            return "balance"
        if x0 >= _KCB_ONLINE_MONEY_IN_X_MIN:
            return "money_in"
        if x0 >= _KCB_ONLINE_MONEY_OUT_X_MIN:
            return "money_out"

    if x0 >= _KCB_ONLINE_REF_X_MIN and not is_amount:
        return "reference"

    if _KCB_ONLINE_DESC_X_MIN <= x0 <= _KCB_ONLINE_DESC_X_MAX and not is_amount:
        return "inline_desc"

    return None


def extract_kcb_online_pdf(file_path: str) -> ExtractionResult:
    """Extract transactions from a KCB Online Banking portal PDF statement."""
    transactions: List[RawTransaction] = []
    warnings: List[WarningItem] = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            if not words:
                continue

            words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))

            # ── Find anchor rows (transaction-date positions) ──────────────────
            anchor_tops = [
                w["top"]
                for w in words_sorted
                if _KCB_ONLINE_TXN_DATE_X_MIN <= w["x0"] <= _KCB_ONLINE_TXN_DATE_X_MAX
                and _KCB_ONLINE_DATE_PAT.match(w["text"])
            ]
            if not anchor_tops:
                continue

            # ── Build anchor objects with amounts / reference ──────────────────
            anchors = []
            for at in anchor_tops:
                row_words = [
                    w for w in words_sorted
                    if abs(w["top"] - at) <= _KCB_ONLINE_ROW_TOLERANCE
                ]
                date_words = [
                    w for w in row_words
                    if _KCB_ONLINE_TXN_DATE_X_MIN <= w["x0"] <= _KCB_ONLINE_TXN_DATE_X_MAX
                    and _KCB_ONLINE_DATE_PAT.match(w["text"])
                ]
                if not date_words:
                    continue

                money_out = money_in = balance = reference = ""
                inline_desc_words: List[dict] = []

                for w in row_words:
                    col = _kcb_online_anchor_column(w)
                    if col == "money_out" and not money_out:
                        money_out = w["text"]
                    elif col == "money_in" and not money_in:
                        money_in = w["text"]
                    elif col == "balance":
                        balance = w["text"]
                    elif col == "reference" and not reference:
                        reference = w["text"]
                    elif col == "inline_desc":
                        inline_desc_words.append(w)

                anchors.append({
                    "top": at,
                    "date_raw": _parse_kcb_online_date(date_words[0]["text"]) or "",
                    "money_out": money_out,
                    "money_in": money_in,
                    "balance": balance,
                    "reference": reference,
                    "inline_desc_words": inline_desc_words,
                    "extra_desc_words": [],
                })

            # ── Assign floating description words to nearest anchor ────────────
            for w in words_sorted:
                x0, top, text = w["x0"], w["top"], w["text"]
                if not (_KCB_ONLINE_DESC_X_MIN <= x0 <= _KCB_ONLINE_DESC_X_MAX):
                    continue
                if _KCB_ONLINE_DATE_PAT.match(text) or _KCB_ONLINE_AMOUNT_PAT.match(text):
                    continue
                # Skip words sitting on an anchor row (already captured as inline_desc)
                if any(abs(a["top"] - top) <= _KCB_ONLINE_ROW_TOLERANCE for a in anchors):
                    continue

                nearest = min(anchors, key=lambda a: abs(a["top"] - top))
                # Drop if word is too far above its nearest anchor (header artifacts)
                if nearest["top"] - top > _KCB_ONLINE_DESC_ABOVE_MAX:
                    continue
                nearest["extra_desc_words"].append(w)

            # ── Build RawTransaction for each anchor ───────────────────────────
            for anchor in anchors:
                all_desc = sorted(
                    anchor["extra_desc_words"] + anchor["inline_desc_words"],
                    key=lambda w: (w["top"], w["x0"]),
                )
                description = " ".join(w["text"] for w in all_desc).strip()

                is_b_fwd = "B/FWD" in description.upper()
                debit_raw = "" if is_b_fwd else _clean_kcb_online_amount(anchor["money_out"])
                credit_raw = "" if is_b_fwd else _clean_kcb_online_amount(anchor["money_in"])
                balance_raw = anchor["balance"].replace(",", "") if anchor["balance"] else ""

                transactions.append(
                    RawTransaction(
                        row_index=len(transactions),
                        date_raw=anchor["date_raw"],
                        description=description,
                        debit_raw=debit_raw,
                        credit_raw=credit_raw,
                        balance_raw=balance_raw,
                        source_file=file_path,
                        extraction_confidence=1.0,
                    )
                )

    return ExtractionResult(
        source_file=file_path,
        extractor_type="kcb_online_pdf",
        row_count=len(transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=transactions,
    )


# ─────────────────────────────────────────────────────────────────────────────
# (original kcb_pdf helpers below)
# ─────────────────────────────────────────────────────────────────────────────

def _flush_kcb_pending(
    pending: dict,
    transactions: List[RawTransaction],
    warnings: List[WarningItem],
) -> None:
    desc = pending["description"] or ""
    is_b_fwd = "B/FWD" in desc.upper() or "BALANCE B/FWD" in desc.upper()
    if is_b_fwd:
        pending["debit_raw"] = ""
        pending["credit_raw"] = ""

    transactions.append(
        RawTransaction(
            row_index=pending["row_index"],
            date_raw=pending["date_raw"],
            description=desc,
            debit_raw=pending["debit_raw"],
            credit_raw=pending["credit_raw"],
            balance_raw=pending["balance_raw"],
            source_file=pending["source_file"],
            extraction_confidence=1.0,
        )
    )
