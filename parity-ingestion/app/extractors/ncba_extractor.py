"""
NCBA Bank Kenya PDF statement extractor.

Supports common layouts:
- Date | Description/Narrative | Debit | Credit | Balance
- Date | Value Date | Description | Money Out | Money In | Balance
- Posting Date | Value Date | Bank Reference | Channel Reference |
  Transaction Type | Transaction Details | Debit Amount | Credit Amount |
  Running Balance  (ruled table — see _extract_via_table)
Date formats: DD/MM/YYYY, DD-MM-YYYY, DD Mon YYYY
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Union

import pdfplumber

from app.models import ExtractionResult, RawTransaction, WarningItem
from app.extractors.pdf_document import NormalizedDocument, as_document

# Date patterns (order matters — try most specific first)
_DATE_PAT_DDMMYYYY = re.compile(r"^(\d{1,2}[/-]\d{1,2}[/-]\d{4})\s")
_DATE_PAT_DDMonYYYY = re.compile(r"^(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s")
_AMOUNT_PAT = re.compile(r"[\d,]+\.\d{2}")

MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Header signature for the ruled-table NCBA template — confirmed unique
# against every other supported bank's header text.
_TABLE_HEADER_REQUIRED = {"POSTING DATE", "CHANNEL REFERENCE"}

# Letterhead/branding text only ever appears in roughly the first ~500
# characters of page 1 (company name, account number, statement period).
# Scanning the full statement risked false-positiving whenever a *transaction
# narration* happened to name another bank as a counterparty (e.g. "FROM NCBA
# BANK M-PESA..." in a real, unrelated I&M Bank statement) — that text lives
# well past this point.
_HEADER_SCAN_CHARS = 500


def _normalize_header_cell(c: Optional[str]) -> str:
    return (c or "").replace("\n", " ").strip().upper()


def detect_ncba(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF appears to be an NCBA Bank Kenya statement."""
    try:
        with as_document(source) as doc:
            header_text = doc.pages[0].text[:_HEADER_SCAN_CHARS].upper()
            has_ncba = (
                "NCBA" in header_text
                or ("NIC" in header_text and "CBA" in header_text)
            )
            if has_ncba:
                return True

            # Some NCBA templates render the brand as a logo image only —
            # fingerprint via the unique ruled-table header instead.
            for page in doc.pages[:2]:
                for table in page.extract_tables():
                    if not table:
                        continue
                    header = {_normalize_header_cell(c) for c in table[0]}
                    if _TABLE_HEADER_REQUIRED.issubset(header):
                        return True
            return False
    except Exception:
        return False


def _parse_ncba_date(raw: str) -> Optional[str]:
    """Parse common NCBA date formats to ISO YYYY-MM-DD."""
    if not raw or not raw.strip():
        return None
    s = raw.strip()

    # DD/MM/YYYY or DD-MM-YYYY
    for sep in ["/", "-"]:
        try:
            dt = datetime.strptime(s, f"%d{sep}%m{sep}%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # DD Mon YYYY (e.g. 20 JUL 2023)
    parts = s.split()
    if len(parts) == 3:
        try:
            day = int(parts[0])
            mon = MONTH_MAP.get(parts[1].upper())
            year = int(parts[2])
            if mon is not None:
                return f"{year}-{mon:02d}-{day:02d}"
        except (ValueError, IndexError):
            pass

    return None


def _is_skip_row(desc: str) -> bool:
    t = (desc or "").upper()
    return (
        "PAGE TOTAL" in t
        or "GRAND TOTAL" in t
        or "BALANCE AT PERIOD END" in t
        or "BALANCE B/FWD" in t
        or "OPENING BALANCE" in t
        or t.startswith("NOTE:")
        or "PAGE" in t and "OF" in t
    )


def _parse_ncba_line(line: str) -> Optional[dict]:
    """Parse a transaction line. Returns dict or None if not a valid txn line."""
    line = line.strip()
    if not line:
        return None

    # Try DD/MM/YYYY or DD-MM/YYYY first
    m = _DATE_PAT_DDMMYYYY.match(line)
    if not m:
        m = _DATE_PAT_DDMonYYYY.match(line)
    if not m:
        return None

    date_raw = m.group(1)
    rest = line[len(date_raw) :].strip()

    amounts = _AMOUNT_PAT.findall(rest)
    has_dr = " Dr" in rest or " dr" in rest or " DR" in rest

    if not amounts:
        if "0.00" in rest or rest.strip() in ("0", ""):
            return {
                "date_raw": date_raw,
                "particulars": rest,
                "money_out": "",
                "money_in": "",
                "balance_raw": "",
                "is_opening": "OPENING" in rest.upper() or "B/FWD" in rest.upper(),
            }
        return None

    def strip_amounts(s: str, amts: List[str]) -> str:
        for a in amts:
            s = s.replace(a, " ", 1)
        return re.sub(r"\s+", " ", s).strip()

    if len(amounts) == 3:
        money_out, money_in, balance_raw = amounts[0], amounts[1], amounts[2]
        if has_dr:
            balance_raw = amounts[2] + " Dr"
        particulars = strip_amounts(rest.replace("Dr", "").replace("dr", ""), amounts)
    elif len(amounts) == 2:
        money_out = amounts[0]
        money_in = ""
        balance_raw = amounts[1] + " Dr" if has_dr else amounts[1]
        particulars = strip_amounts(rest.replace("Dr", "").replace("dr", ""), amounts)
    elif len(amounts) == 1:
        money_out = ""
        money_in = "" if has_dr else amounts[0]
        balance_raw = amounts[0] + " Dr" if has_dr else amounts[0]
        particulars = strip_amounts(rest.replace("Dr", "").replace("dr", ""), amounts)
    else:
        money_out = amounts[-3] if len(amounts) >= 3 else ""
        money_in = amounts[-2] if len(amounts) >= 2 else ""
        balance_raw = amounts[-1] + (" Dr" if has_dr else "")
        particulars = strip_amounts(rest.replace("Dr", "").replace("dr", ""), amounts)

    return {
        "date_raw": date_raw,
        "particulars": particulars,
        "money_out": money_out,
        "money_in": money_in,
        "balance_raw": balance_raw,
        "is_opening": False,
    }


def _extract_via_table(file_path: str) -> List[RawTransaction]:
    """
    Table-based extraction for the ruled-table NCBA template. Unlike the
    text-line template below, this one has real ruled borders, so
    extract_tables() returns clean, already-columned rows directly —
    extract_text() on this same file produces garbled, wrapped-mid-word
    output that the regex line parser below can't read.

    Returns [] if no page has a table matching the required header — caller
    falls back to the text-line path for the older NCBA template.
    """
    transactions: List[RawTransaction] = []
    row_idx = 0
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header = [_normalize_header_cell(c) for c in table[0]]
                if not _TABLE_HEADER_REQUIRED.issubset(set(header)):
                    continue
                idx = {name: i for i, name in enumerate(header)}

                def cell(row: List[Optional[str]], col: str) -> str:
                    i = idx.get(col)
                    if i is None or i >= len(row):
                        return ""
                    return (row[i] or "").strip()

                for row in table[1:]:
                    if not row:
                        continue
                    iso_date = _parse_ncba_date(cell(row, "POSTING DATE")) or ""
                    if not iso_date:
                        continue
                    desc = re.sub(r"\s+", " ", cell(row, "TRANSACTION DETAILS").replace("\n", " ")).strip()
                    transactions.append(
                        RawTransaction(
                            row_index=row_idx,
                            date_raw=iso_date,
                            description=desc,
                            debit_raw=cell(row, "DEBIT AMOUNT").replace(",", ""),
                            credit_raw=cell(row, "CREDIT AMOUNT").replace(",", ""),
                            balance_raw=cell(row, "RUNNING BALANCE").replace(",", ""),
                            source_file=file_path,
                            extraction_confidence=1.0,
                        )
                    )
                    row_idx += 1
    return transactions


def extract_ncba_pdf(file_path: str) -> ExtractionResult:
    table_transactions = _extract_via_table(file_path)
    if table_transactions:
        return ExtractionResult(
            source_file=file_path,
            extractor_type="ncba_pdf",
            row_count=len(table_transactions),
            extraction_status="success",
            warnings=[],
            raw_transactions=table_transactions,
        )

    transactions: List[RawTransaction] = []
    warnings: List[WarningItem] = []
    row_idx = 0

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            in_transactions = False
            for line in text.split("\n"):
                # Detect transaction section by common header patterns
                line_upper = line.upper()
                if (
                    ("DATE" in line_upper or "TXN DATE" in line_upper or "TRANSACTION DATE" in line_upper)
                    and ("DEBIT" in line_upper or "MONEY OUT" in line_upper or "DR" in line_upper)
                    and ("CREDIT" in line_upper or "MONEY IN" in line_upper or "CR" in line_upper)
                ):
                    in_transactions = True
                    continue
                if (
                    "DATE" in line_upper
                    and ("DESCRIPTION" in line_upper or "NARRATIVE" in line_upper or "PARTICULARS" in line_upper)
                    and ("BALANCE" in line_upper or "AMOUNT" in line_upper)
                ):
                    in_transactions = True
                    continue

                if not in_transactions:
                    continue

                parsed = _parse_ncba_line(line)
                if not parsed:
                    if line.strip() == "0.00":
                        parsed = {
                            "date_raw": "",
                            "particulars": "Opening Balance",
                            "money_out": "",
                            "money_in": "",
                            "balance_raw": "0.00",
                            "is_opening": True,
                        }
                    else:
                        continue

                if _is_skip_row(parsed["particulars"]):
                    continue

                iso_date = _parse_ncba_date(parsed["date_raw"]) or ""
                balance_raw = parsed.get("balance_raw", "")
                balance_str = (
                    balance_raw.replace("Dr", "").replace("dr", "").strip()
                    if balance_raw
                    else ""
                )

                debit_raw = (
                    parsed["money_out"].replace(",", "").lstrip("-")
                    if parsed.get("money_out")
                    else ""
                )
                credit_raw = (
                    parsed["money_in"].replace(",", "")
                    if parsed.get("money_in")
                    else ""
                )

                if parsed.get("is_opening"):
                    debit_raw = ""
                    credit_raw = ""

                transactions.append(
                    RawTransaction(
                        row_index=row_idx,
                        date_raw=iso_date,
                        description=parsed["particulars"],
                        debit_raw=debit_raw,
                        credit_raw=credit_raw,
                        balance_raw=balance_str,
                        source_file=file_path,
                        extraction_confidence=1.0,
                    )
                )
                row_idx += 1

    return ExtractionResult(
        source_file=file_path,
        extractor_type="ncba_pdf",
        row_count=len(transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=transactions,
    )


# ---------------------------------------------------------------------------
# NCBA "e-Statement Of Account" template (PAR-69) — a third NCBA layout,
# distinct from both templates above (`Date | Transaction Type and Details |
# Value Date | Debit | Credit | Balance`, but debit/credit render as a
# single trailing amount, not two columns). It is routinely
# password-protected, unlike the other two templates.
#
# Direction has no reliable in-text marker: some debit rows carry a "- Dr"
# suffix in the transaction type (e.g. "Outward Cheque - Dr") but most don't
# (e.g. "Excise Duty", "AA Loan Repayment" are debits with no marker at
# all). Direction is instead derived from the running-balance delta — this
# line's balance vs. the previous one — which is the balance-delta
# comparison PAR-14 found missing from coop_extractor's Layout C stub,
# implemented here for real. Verified against a real fixture
# (NCBA_Jan2024.pdf, GREENFOREST FOODS LIMITED): summing amounts by
# inferred direction reproduces the statement's own printed "Payments In"
# (17,760,978.36) and "Payments Out" (18,378,707.22) totals exactly, and the
# running balance chain lands on the printed "Closing Balance" (813,198.41)
# to the cent — including through a stretch of negative (overdrawn)
# balances, which is why the balance/amount regex below allows a leading
# "-". Cross-checked against a second real fixture too (NCBA - JAN 2025.pdf,
# same client, different statement, "Go Banking" account variant) with the
# same exact-to-the-cent reconciliation.
#
# The header casing isn't stable across statements — "e-Statement Of
# Account" (Jan 2024) vs. "e-Statement of Account" (Jan 2025) — so detection
# below is case-insensitive.
#
# SCOPE NOTE: these two functions take `password` directly and open their
# own `pdfplumber.PDF` — they are deliberately NOT wired into the shared
# `pdf_document.py` single-parse layer or `router.py`'s auto-detection
# chain. Where a password comes from at parse time in production
# (per-document field vs. per-client config vs. something else) is an open
# design decision tracked separately under PAR-69 and is not decided here;
# wiring these into the shared plumbing is follow-up work once that
# decision is made.
# ---------------------------------------------------------------------------

_ESTATEMENT_LINE_PAT = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(.*?)\s+\d{2}/\d{2}/\d{4}\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})$"
)
_ESTATEMENT_OPENING_PAT = re.compile(r"Opening Balance\s+(-?[\d,]+\.\d{2})")


def detect_ncba_estatement(file_path: str, password: Optional[str] = None) -> bool:
    """Return True if the PDF is the NCBA "e-Statement Of Account" template.

    Opens with `password` directly (this template is routinely
    password-protected); a wrong/missing password, or any other failure to
    open, returns False rather than raising — same contract as every other
    `detect_*` in this module.
    """
    try:
        with pdfplumber.open(file_path, password=password) as pdf:
            header = (pdf.pages[0].extract_text() or "")[:600]
            header_upper = header.upper()
            return (
                "E-STATEMENT" in header_upper and "OF ACCOUNT" in header_upper
                and "TRANSACTION TYPE AND DETAILS" in header_upper
            )
    except Exception:
        return False


def extract_ncba_estatement_pdf(file_path: str, password: Optional[str] = None) -> ExtractionResult:
    """Extract the NCBA "e-Statement Of Account" template.

    See the module note above for why direction is derived from the
    running-balance delta rather than any in-text Dr/Cr marker.
    """
    transactions: List[RawTransaction] = []
    warnings: List[WarningItem] = []
    row_idx = 0
    prev_balance: Optional[Decimal] = None

    with pdfplumber.open(file_path, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            if prev_balance is None:
                m = _ESTATEMENT_OPENING_PAT.search(text)
                if m:
                    prev_balance = Decimal(m.group(1).replace(",", ""))

            for line in text.split("\n"):
                m = _ESTATEMENT_LINE_PAT.match(line.strip())
                if not m:
                    continue

                date_raw, desc, amt_raw, bal_raw = m.groups()
                amount = Decimal(amt_raw.replace(",", ""))
                balance = Decimal(bal_raw.replace(",", ""))

                if prev_balance is None:
                    # No "Opening Balance" line found before the first
                    # transaction — shouldn't happen on a real statement,
                    # but flag rather than silently guess a direction.
                    warnings.append(
                        WarningItem(
                            row_index=row_idx,
                            message=(
                                "e-statement: no opening balance found before "
                                "first transaction; direction defaulted to credit"
                            ),
                            raw_text=line.strip(),
                        )
                    )
                    is_credit = True
                else:
                    is_credit = balance >= prev_balance
                prev_balance = balance

                iso_date = _parse_ncba_date(date_raw) or ""
                transactions.append(
                    RawTransaction(
                        row_index=row_idx,
                        date_raw=iso_date,
                        description=desc.strip(),
                        debit_raw="" if is_credit else str(amount),
                        credit_raw=str(amount) if is_credit else "",
                        balance_raw=str(balance),
                        source_file=file_path,
                        extraction_confidence=1.0,
                    )
                )
                row_idx += 1

    return ExtractionResult(
        source_file=file_path,
        extractor_type="ncba_estatement_pdf",
        row_count=len(transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=transactions,
    )
