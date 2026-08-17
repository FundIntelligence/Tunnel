"""
Inline KCB iBANK (Online portal format) parser for the Render backend.

Used as a fallback when the parity-ingestion service returns 415 (bank format
not recognised) for files that are actually KCB Online PDFs.  Only requires
pdfplumber, which is already in the backend's requirements.

Produces rows in the same format expected by _parity_result_to_rows callers.
"""
from __future__ import annotations

import hashlib
import re
import tempfile
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

# ── Detection strings (case-sensitive, same as parity-ingestion) ──────────────
_KCB_ONLINE_DATE_PAT = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_KCB_ONLINE_AMOUNT_PAT = re.compile(r"^-?[\d,]+\.\d{2}$")

# X-thresholds from the Buildex / GBFund KCB Online statement layout
_TXN_DATE_X_MIN = 45.0
_TXN_DATE_X_MAX = 120.0
_DESC_X_MIN = 220.0
_DESC_X_MAX = 455.0
_MONEY_OUT_X_MIN = 450.0
_MONEY_OUT_X_MAX = 548.0
_MONEY_IN_X_MIN = 548.0
_MONEY_IN_X_MAX = 648.0
_BALANCE_X_MIN = 648.0
_REF_X_MIN = 715.0
_ROW_TOLERANCE = 3.5
_DESC_ABOVE_MAX = 22.0


def detect_kcb_online_bytes(file_bytes: bytes) -> bool:
    """Return True if the bytes look like a KCB iBANK Online statement."""
    try:
        with pdfplumber.open(_bytes_to_path(file_bytes)) as pdf:
            if not pdf.pages:
                return False
            text = pdf.pages[0].extract_text() or ""
            return (
                "Account Statement" in text
                and "Money In" in text
                and "Money Out" in text
                and "Ledger Balance" in text
                and bool(re.search(r"\d{2}\.\d{2}\.\d{4}", text))
            )
    except Exception:
        return False


def _bytes_to_path(file_bytes: bytes) -> str:
    """Write bytes to a temp file; caller is responsible for cleanup."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(file_bytes)
    tmp.flush()
    tmp.close()
    return tmp.name


def _parse_online_date(s: str) -> Optional[str]:
    try:
        dt = datetime.strptime(s.strip(), "%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _clean_amount(raw: str) -> str:
    """Strip commas/sign; return '' for zero or empty."""
    if not raw:
        return ""
    cleaned = raw.replace(",", "").lstrip("-").strip()
    if cleaned in ("0.00", "0", ""):
        return ""
    return cleaned


def _to_cents(amount_str: str) -> int:
    if not amount_str:
        return 0
    try:
        v = Decimal(amount_str)
        return int((v * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
    except Exception:
        return 0


def _anchor_column(w: dict) -> Optional[str]:
    x0 = w["x0"]
    text = w["text"]
    is_amount = bool(_KCB_ONLINE_AMOUNT_PAT.match(text))

    if is_amount:
        if x0 >= _BALANCE_X_MIN:
            return "balance"
        if x0 >= _MONEY_IN_X_MIN:
            return "money_in"
        if x0 >= _MONEY_OUT_X_MIN:
            return "money_out"

    if x0 >= _REF_X_MIN and not is_amount:
        return "reference"

    if _DESC_X_MIN <= x0 <= _DESC_X_MAX and not is_amount:
        return "inline_desc"

    return None


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _compute_txn_id(document_id: str, txn_date: str, signed_cents: int, desc_norm: str) -> str:
    basis = "|".join([document_id, "default", txn_date, str(signed_cents), desc_norm])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def extract_kcb_online_rows(
    file_bytes: bytes,
    document_id: str,
) -> List[Dict[str, Any]]:
    """
    Parse a KCB Online PDF from bytes and return backend-format transaction rows.

    Rows with zero signed_cents (e.g. B/FWD) are dropped, matching the
    behaviour of the parity-ingestion client's _parity_result_to_rows.
    """
    path = _bytes_to_path(file_bytes)
    rows: List[Dict[str, Any]] = []

    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                words = page.extract_words()
                if not words:
                    continue

                words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))

                anchor_tops = [
                    w["top"]
                    for w in words_sorted
                    if _TXN_DATE_X_MIN <= w["x0"] <= _TXN_DATE_X_MAX
                    and _KCB_ONLINE_DATE_PAT.match(w["text"])
                ]
                if not anchor_tops:
                    continue

                anchors = []
                for at in anchor_tops:
                    row_words = [w for w in words_sorted if abs(w["top"] - at) <= _ROW_TOLERANCE]
                    date_words = [
                        w for w in row_words
                        if _TXN_DATE_X_MIN <= w["x0"] <= _TXN_DATE_X_MAX
                        and _KCB_ONLINE_DATE_PAT.match(w["text"])
                    ]
                    if not date_words:
                        continue

                    money_out = money_in = balance = ""
                    inline_desc: List[dict] = []

                    for w in row_words:
                        col = _anchor_column(w)
                        if col == "money_out" and not money_out:
                            money_out = w["text"]
                        elif col == "money_in" and not money_in:
                            money_in = w["text"]
                        elif col == "balance":
                            balance = w["text"]
                        elif col == "inline_desc":
                            inline_desc.append(w)

                    anchors.append({
                        "top": at,
                        "date_raw": _parse_online_date(date_words[0]["text"]) or "",
                        "money_out": money_out,
                        "money_in": money_in,
                        "inline_desc": inline_desc,
                        "extra_desc": [],
                    })

                for w in words_sorted:
                    x0, top, text = w["x0"], w["top"], w["text"]
                    if not (_DESC_X_MIN <= x0 <= _DESC_X_MAX):
                        continue
                    if _KCB_ONLINE_DATE_PAT.match(text) or _KCB_ONLINE_AMOUNT_PAT.match(text):
                        continue
                    if any(abs(a["top"] - top) <= _ROW_TOLERANCE for a in anchors):
                        continue
                    nearest = min(anchors, key=lambda a: abs(a["top"] - top))
                    if nearest["top"] - top > _DESC_ABOVE_MAX:
                        continue
                    nearest["extra_desc"].append(w)

                for anchor in anchors:
                    all_desc = sorted(
                        anchor["extra_desc"] + anchor["inline_desc"],
                        key=lambda w: (w["top"], w["x0"]),
                    )
                    description = " ".join(w["text"] for w in all_desc).strip()

                    is_b_fwd = "B/FWD" in description.upper()
                    debit_raw = "" if is_b_fwd else _clean_amount(anchor["money_out"])
                    credit_raw = "" if is_b_fwd else _clean_amount(anchor["money_in"])

                    debit_cents = _to_cents(debit_raw)
                    credit_cents = _to_cents(credit_raw)
                    signed_cents = credit_cents - debit_cents

                    if signed_cents == 0:
                        continue

                    txn_date = anchor["date_raw"]
                    if not txn_date:
                        continue

                    desc_norm = _normalize(description)
                    txn_id = _compute_txn_id(document_id, txn_date, signed_cents, desc_norm)

                    rows.append({
                        "txn_date": txn_date,
                        "signed_amount_cents": signed_cents,
                        "abs_amount_cents": abs(signed_cents),
                        "raw_descriptor": description,
                        "parsed_descriptor": description.strip(),
                        "normalized_descriptor": desc_norm,
                        # Per-document account_id enables transfer detection — see PAR-30.
                        "account_id": str(document_id),
                        "txn_id": txn_id,
                    })
    finally:
        import os
        try:
            os.unlink(path)
        except OSError:
            pass

    return rows
