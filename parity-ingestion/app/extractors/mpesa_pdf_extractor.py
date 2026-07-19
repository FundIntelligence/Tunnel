"""
M-Pesa PDF full statement extractor.

Separate from mpesa_extractor.py (CSV). Do not modify or import from mpesa_extractor.py.

Columns: Receipt No | Completion Time | Details | Transaction Status | Paid in | Withdrawn | Balance
Date: YYYY-MM-DD HH:MM:SS — take first 10 chars for ISO date.
Status filter: Transaction Status == "Completed" (case-insensitive). Discard others.
Paid in → positive amount (credit_raw). Withdrawn → negative (debit_raw).
"""
from __future__ import annotations

from typing import List, Union

import pdfplumber

from app.models import ExtractionResult, RawTransaction, WarningItem
from app.extractors.pdf_document import NormalizedDocument, as_document


def detect_mpesa_pdf(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF appears to be an M-Pesa full statement."""
    try:
        with as_document(source) as doc:
            text = doc.text_upto(2)
            return (
                ("MPESA FULL STATEMENT" in text or "M-PESA STATEMENT" in text)
                and "Safaricom" in text
                and "Receipt No" in text
            )
    except Exception:
        return False


def _parse_mpesa_date(completion_time: str) -> str:
    """Extract YYYY-MM-DD from 'YYYY-MM-DD HH:MM:SS' format."""
    if not completion_time or len(completion_time) < 10:
        return ""
    return completion_time.strip()[:10]


def _to_float(s: str) -> float:
    try:
        return float(str(s).replace(",", "")) if s else 0.0
    except Exception:
        return 0.0


def _deduplicate_by_receipt(records: List[dict]) -> List[dict]:
    """Keep only the row with positive amount per receipt. If both positive, keep first."""
    from collections import defaultdict
    by_receipt: dict[str, List[dict]] = defaultdict(list)
    for r in records:
        receipt = r.get("receipt", "") or ""
        by_receipt[receipt or f"_no_receipt_{id(r)}"].append(r)
    kept: List[dict] = []
    for receipt, rows in by_receipt.items():
        positive = [r for r in rows if _to_float(r.get("credit_raw", "")) > 0 or _to_float(r.get("debit_raw", "")) > 0]
        if positive:
            kept.append(positive[0])
        else:
            kept.append(rows[0])
    return kept


def extract_mpesa_pdf(file_path: str) -> ExtractionResult:
    records: List[dict] = []
    warnings: List[WarningItem] = []

    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables or []:
                    header_idx: int | None = None
                    for i, row in enumerate(table):
                        if not row or len(row) < 6:
                            continue
                        first = (row[0] or "").strip()
                        if "Receipt No" in first or "Receipt No" in str(row):
                            header_idx = i
                            break

                    if header_idx is None:
                        continue

                    for row in table[header_idx + 1 :]:
                        if len(row) < 6:
                            continue

                        receipt = (row[0] or "").strip()
                        completion_time = (row[1] or "").strip()
                        details = (row[2] or "").strip().replace("\n", " ")
                        status = (row[3] or "").strip()
                        paid_in = (row[4] or "").strip()
                        withdrawn = (row[5] or "").strip()
                        balance = (row[6] if len(row) > 6 else "") or ""
                        balance = balance.strip()

                        if not completion_time and not details:
                            continue

                        if status.upper() != "COMPLETED":
                            continue

                        date_raw = _parse_mpesa_date(completion_time)
                        if not date_raw:
                            continue

                        if paid_in:
                            debit_raw = ""
                            credit_raw = paid_in.replace(",", "")
                        elif withdrawn:
                            debit_raw = withdrawn.replace(",", "").lstrip("-")
                            credit_raw = ""
                        else:
                            debit_raw = ""
                            credit_raw = ""

                        records.append({
                            "receipt": receipt,
                            "date_raw": date_raw,
                            "description": details,
                            "debit_raw": debit_raw,
                            "credit_raw": credit_raw,
                            "balance_raw": balance,
                        })

        before_count = len(records)
        records = _deduplicate_by_receipt(records)
        transactions = [
            RawTransaction(
                row_index=i,
                date_raw=r["date_raw"],
                description=r["description"],
                debit_raw=r["debit_raw"],
                credit_raw=r["credit_raw"],
                balance_raw=r["balance_raw"],
                source_file=file_path,
                extraction_confidence=1.0,
            )
            for i, r in enumerate(records)
        ]
        setattr(extract_mpesa_pdf, "_last_before_dedup", before_count)

    except Exception as e:
        return ExtractionResult(
            source_file=file_path,
            extractor_type="mpesa_pdf",
            row_count=0,
            extraction_status="failed",
            warnings=[
                WarningItem(row_index=0, message=str(e), raw_text=""),
            ],
            raw_transactions=[],
        )

    return ExtractionResult(
        source_file=file_path,
        extractor_type="mpesa_pdf",
        row_count=len(transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=transactions,
    )
