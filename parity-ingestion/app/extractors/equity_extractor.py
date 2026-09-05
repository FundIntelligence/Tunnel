"""
Equity Bank Kenya PDF statement extractor.

Personal format:
  Columns: Date | Value | Particulars | Money Out | Money In | Balance
  Header: STATEMENT OF ACCOUNT + EQUITY + Particulars / Money Out / Money In

Business format (DD-MM-YYYY):
  Header: Account Statement + Narrative / Debit / Credit / Running Balance
  Transaction Date + Value Date (value date ignored) + narrative + amounts

CLMS format (Cash and Liquidity Management System, DD/MM/YYYY):
  Header: Account Statement + "EQUITY BANK ACCOUNT FOR CASH AND LIQUIDITY MGT SYSTEM"
         + Narrative / Debit / Credit / Running Balance + "Total Count: N"
  Coordinate-based extraction — amounts right-aligned in separate debit/credit/balance zones.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, List, Optional, Tuple, Union

import pdfplumber

from app.models import ExtractionResult, RawTransaction, WarningItem
from app.extractors.pdf_document import NormalizedDocument, as_document

logger = logging.getLogger(__name__)

_DATE_PAT = re.compile(r"^(\d{2}-\d{2}-\d{4})\s")
_DATE2_PAT = re.compile(r"^(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})\s+(.*)$")
_DATE1_BUS_PAT = re.compile(r"^(\d{2}-\d{2}-\d{4})\s+(.*)$")
_AMOUNT_PAT = re.compile(r"[\d,]+\.\d{2}")

# Page-chunked extraction for large PDFs (avoids long single-pass CPU time on small instances)
EQUITY_PAGE_CHUNK_SIZE = 20

# April 2025 split-date layout (coordinate-based extraction)
_APR_DATE_PREFIX_PAT = re.compile(r"^(\d{2})-(\d{2})-$")
_APR_YEAR_PAT = re.compile(r"^(20\d{2})$")
_APR_AMOUNT_PAT = re.compile(r"^[\d,]+\.\d{2}$")
# Some statements concatenate amount+reference with no space (e.g. "1,938.00q5LCQ...")
_APR_AMOUNT_PREFIX_PAT = re.compile(r"^([\d,]+\.\d{2})")
_APR_DATE_X_MIN = 38
_APR_DATE_X_MAX = 80
_APR_NARR_X_MIN = 115
_APR_NARR_X_MAX = 280
_APR_DEBIT_X_MIN = 280
_APR_DEBIT_CREDIT_X = 345
_APR_BALANCE_X_MIN = 440
_APR_DATA_TOP_MIN = 232


class _BusinessParserState:
    """Mutable state for business-layout extraction (must continue across page chunks)."""

    __slots__ = ("seen_table", "buffer", "previous_balance", "row_idx", "transactions")

    def __init__(self) -> None:
        self.seen_table = False
        self.buffer: List[str] = []
        self.previous_balance: Optional[int] = None
        self.row_idx = 0
        self.transactions: List[RawTransaction] = []


class _PersonalParserState:
    __slots__ = ("row_idx", "transactions")

    def __init__(self) -> None:
        self.row_idx = 0
        self.transactions: List[RawTransaction] = []


def _detect_split_transaction_header(lines: List[str]) -> bool:
    """
    Some Equity business PDFs break the column header across lines, e.g.:
      Transacti Value Transaction Cheque
      Narrative Debit Credit Running Balance
      on Date Date Reference Number
    """
    for i, line in enumerate(lines):
        if "Transacti" not in line:
            continue
        window = "\n".join(lines[i : min(i + 3, len(lines))])
        if "on Date" in window:
            return True
    return False


def _is_split_date_layout(first_page_lines: List[str]) -> bool:
    """True if the PDF uses the April 2025 split-date column layout."""
    return _detect_split_transaction_header(first_page_lines)


def _normalize_equity_split_date_block_lines(lines: List[str]) -> List[str]:
    """
    Merge split date + amount + year lines into one logical row matching standard layout.

    Layout variant (April 2025 and similar):
      01-04- 30-03-
      TCU4O61UKS S46462411 6,387.00 1,117,741.00
      2025 2025
    ->  01-04-2025 30-03-2025 TCU4O61UKS S46462411 6,387.00 1,117,741.00
    """
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if i + 2 < n:
            m = re.match(r"^(\d{2}-\d{2}-)\s+(\d{2}-\d{2}-)\s*$", s)
            y = re.match(r"^(\d{4})\s+(\d{4})\s*$", lines[i + 2].strip())
            mid = lines[i + 1].strip()
            if m and y and _AMOUNT_PAT.search(mid):
                d1 = f"{m.group(1)}{y.group(1)}"
                d2 = f"{m.group(2)}{y.group(2)}"
                out.append(f"{d1} {d2} {mid}")
                i += 3
                continue
        out.append(lines[i])
        i += 1
    return out


def _is_equity_business_format(text: str) -> bool:
    """Equity business account PDF: Account Statement + Debit/Credit/Running Balance columns.

    pdfplumber renders the 'Running Balance' column header across two lines
    ('Running' / 'Balance') so we check for the words independently.
    """
    return (
        "Account Statement" in text
        and "Debit" in text
        and "Credit" in text
        and ("Running Balance" in text or ("Running" in text and "Balance" in text))
    )


def detect_equity(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF appears to be an Equity Bank statement (personal or business)."""
    try:
        with as_document(source) as doc:
            text = doc.text_upto(2)
            if _is_equity_business_format(text):
                return True
            text_upper = text.upper()
            has_stmt = "STATEMENT OF ACCOUNT" in text_upper
            has_equity = "EQUITY" in text_upper
            has_cols = (
                "PARTICULARS" in text_upper
                and "MONEY OUT" in text_upper
                and "MONEY IN" in text_upper
            )
            return bool(has_stmt and has_equity and has_cols)
    except Exception:
        return False


def _parse_equity_date(raw: str) -> Optional[str]:
    """Parse DD-MM-YYYY to ISO YYYY-MM-DD."""
    if not raw or not raw.strip():
        return None
    try:
        dt = datetime.strptime(raw.strip(), "%d-%m-%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _is_valid_transaction_date(date_str: str) -> bool:
    """Reject dates more than 5 years from today — parser artifact guard."""
    from datetime import date as _date
    try:
        parsed = _date.fromisoformat(date_str)
        max_allowed = _date.today().replace(year=_date.today().year + 5)
        return parsed <= max_allowed
    except (ValueError, TypeError):
        return False


def _parse_equity_balance(raw: str) -> Tuple[int, bool]:
    """
    Parse balance. Strip "Dr" suffix for overdrawn. Return (cents, is_overdrawn).
    Always returns positive cents.
    """
    if not raw or not raw.strip():
        return 0, False

    s = raw.strip()
    is_overdrawn = s.upper().endswith("DR")
    clean = s.replace("Dr", "").replace("dr", "").strip()

    if not clean:
        return 0, is_overdrawn

    clean = clean.replace(",", "")
    if clean.startswith("-"):
        clean = clean[1:]

    try:
        if "." in clean:
            whole_str, frac_str = clean.split(".", 1)
            frac_str = frac_str.ljust(2, "0")[:2]
            whole = int(whole_str) if whole_str else 0
            frac = int(frac_str)
            return whole * 100 + frac, is_overdrawn
        return int(clean) * 100, is_overdrawn
    except ValueError:
        return 0, False


def _is_skip_row(desc: str) -> bool:
    t = (desc or "").upper()
    return (
        "PAGE TOTAL" in t
        or "GRAND TOTAL" in t
        or "UNCLEARED CHEQUES" in t
        or t.startswith("NOTE: ANY OMISSION")
        or t.startswith("DO YOU NEED FOREIGN EXCHANGE")
    )


def _strip_amounts_from_rest(rest: str, amts: List[str]) -> str:
    s = rest
    for a in amts:
        s = s.replace(a, " ", 1)
    s = s.replace("Dr", "").replace("dr", "")
    return re.sub(r"\s+", " ", s).strip()


def _parse_equity_line(line: str) -> Optional[dict]:
    """Parse a personal-format transaction line. Returns dict or None if not a valid txn line."""
    line = line.strip()
    if not line:
        return None

    m = _DATE_PAT.match(line)
    if not m:
        return None

    date_raw = m.group(1)
    rest = line[len(date_raw) :].strip()

    amounts = _AMOUNT_PAT.findall(rest)
    has_dr = " Dr" in rest or " dr" in rest

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


def _amount_str_to_cents(s: str) -> int:
    t = s.replace(",", "").strip()
    if not t:
        return 0
    neg = t.startswith("-")
    if neg:
        t = t[1:]
    if "." in t:
        w, f = t.split(".", 1)
        f = (f + "00")[:2]
        v = int(w or 0) * 100 + int(f)
    else:
        v = int(t) * 100
    return -v if neg else v


def _cents_to_equity_raw(cents: Optional[int]) -> str:
    if cents is None or cents == 0:
        return ""
    neg = cents < 0
    c = abs(cents)
    body = f"{c // 100}.{c % 100:02d}"
    return f"-{body}" if neg else body


def _parse_equity_business_amounts_from_rest(
    rest: str, previous_balance: Optional[int] = None
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Parse debit/credit/balance from Equity business statement amount line.

    Only decimal money tokens (x,xxx.yy) are considered — avoids matching dates.

    Pattern:
    - 2 numbers: [Amount, Balance] — debit if balance fell, credit if balance rose
      (first row with no previous balance: treat as [Debit, Balance])
    - 1 number: balance-only fragment
    - 3 numbers: [Debit, Credit, Balance]
    - More than 3: use last three as debit, credit, balance

    Returns: (debit_cents, credit_cents, balance_cents) — None for absent debit/credit.
    """
    matches = _AMOUNT_PAT.findall(rest)
    if not matches:
        return None, None, None

    amounts_cents = [_amount_str_to_cents(x) for x in matches]

    if len(amounts_cents) == 1:
        return None, None, amounts_cents[0]

    if len(amounts_cents) == 2:
        amount, balance = amounts_cents[0], amounts_cents[1]
        if previous_balance is not None:
            if balance < previous_balance:
                return amount, None, balance
            if balance > previous_balance:
                return None, amount, balance
            return None, None, balance
        # No prior balance: two tokens = [Debit, Balance] (business layout default)
        return amount, None, balance

    if len(amounts_cents) == 3:
        return amounts_cents[0], amounts_cents[1], amounts_cents[2]

    return amounts_cents[-3], amounts_cents[-2], amounts_cents[-1]


def _parse_equity_business_amounts(
    line: str, previous_balance: Optional[int] = None
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    m = _DATE2_PAT.match(line.strip())
    if not m:
        return None, None, None
    return _parse_equity_business_amounts_from_rest(m.group(3).strip(), previous_balance)


def _clean_equity_business_description(desc: str) -> str:
    """Remove header artifacts from business statement descriptions."""
    patterns_to_remove = [
        r"^n Date Date Reference\s+",
        r"^Date Date Reference\s+",
        r"^Transaction Date Value Date\s+",
        r"^Transacti Value Transaction Cheque\s+",
        r"^on Date Date Reference Number\s+",
        r"^Narrative\s+Debit\s+Credit\s+",
        r"^Reference\s+",
    ]

    cleaned = desc
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _parse_business_txn_line(
    line: str,
    narrative_prefix: str,
    previous_balance: Optional[int] = None,
) -> Tuple[Optional[dict], Optional[int]]:
    """
    Parse a business-format line: TransactionDate ValueDate rest...
    Returns (parsed_row_dict_or_None, new_running_balance_cents_or_None).
    """
    stripped = line.strip()
    m = _DATE2_PAT.match(stripped)
    if m:
        txn_date = m.group(1)
        rest = m.group(3).strip()
    else:
        m1 = _DATE1_BUS_PAT.match(stripped)
        if not m1:
            return None, None
        txn_date = m1.group(1)
        rest = m1.group(2).strip()
    amounts = _AMOUNT_PAT.findall(rest)
    has_dr = " Dr" in rest or " dr" in rest

    if not amounts:
        if "0.00" in rest or rest.strip() in ("0", ""):
            inline = _strip_amounts_from_rest(rest, [])
            particulars = _clean_equity_business_description(
                (narrative_prefix + " " + inline).strip()
            )
            return (
                {
                    "date_raw": txn_date,
                    "particulars": particulars,
                    "money_out": "",
                    "money_in": "",
                    "balance_raw": "",
                    "is_opening": "OPENING" in particulars.upper()
                    or "B/FWD" in particulars.upper(),
                },
                previous_balance,
            )
        return None, previous_balance

    debit_cents, credit_cents, balance_cents = _parse_equity_business_amounts_from_rest(
        rest, previous_balance
    )

    balance_raw = amounts[-1] + (" Dr" if has_dr else "")

    particulars_inline = _strip_amounts_from_rest(
        rest.replace("Dr", "").replace("dr", ""), amounts
    )
    particulars = _clean_equity_business_description(
        (narrative_prefix + " " + particulars_inline).strip()
    )

    if (
        debit_cents is None
        and credit_cents is None
        and balance_cents is not None
        and len(amounts) == 1
    ):
        # Balance-only line — advance running balance, no transaction row
        return None, balance_cents

    if debit_cents is None and credit_cents is None and len(amounts) >= 2:
        # No movement (e.g. flat balance) — still advance balance
        return None, balance_cents

    return (
        {
            "date_raw": txn_date,
            "particulars": particulars,
            "money_out": _cents_to_equity_raw(debit_cents) if debit_cents else "",
            "money_in": _cents_to_equity_raw(credit_cents) if credit_cents else "",
            "balance_raw": balance_raw,
            "is_opening": False,
        },
        balance_cents,
    )


def _append_raw_transaction(
    transactions: List[RawTransaction],
    parsed: dict,
    file_path: str,
    row_idx: int,
) -> int:
    if _is_skip_row(parsed["particulars"]):
        return row_idx

    iso_date = _parse_equity_date(parsed["date_raw"]) or ""
    if iso_date and not _is_valid_transaction_date(iso_date):
        return row_idx  # skip this row — date is a parser artifact
    balance_raw = parsed["balance_raw"]
    balance_str = (
        balance_raw.replace("Dr", "").replace("dr", "").strip()
        if balance_raw
        else ""
    )

    debit_raw = (
        parsed["money_out"].replace(",", "").lstrip("-")
        if parsed["money_out"]
        else ""
    )
    credit_raw = (
        parsed["money_in"].replace(",", "")
        if parsed["money_in"]
        else ""
    )

    if parsed.get("is_opening"):
        debit_raw = ""
        credit_raw = ""

    is_overdrawn = bool(balance_raw and ("Dr" in balance_raw or "dr" in balance_raw))

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
            balance_is_overdrawn=is_overdrawn if is_overdrawn else None,
        )
    )
    return row_idx + 1


def _run_personal_on_pages(
    pages: List[Any],
    file_path: str,
    state: _PersonalParserState,
) -> None:
    """
    Personal-format extraction for a sequence of pdfplumber pages (mutates state).
    """
    for page in pages:
        text = page.extract_text()
        if not text:
            page.flush_cache()
            continue

        in_transactions = False
        for line in text.split("\n"):
            if "Date" in line and "Particulars" in line and "Money Out" in line:
                in_transactions = True
                continue
            if not in_transactions:
                continue

            parsed = _parse_equity_line(line)
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

            state.row_idx = _append_raw_transaction(
                state.transactions, parsed, file_path, state.row_idx
            )
        page.flush_cache()


def _extract_equity_personal(pdf: Any, file_path: str) -> List[RawTransaction]:
    state = _PersonalParserState()
    _run_personal_on_pages(pdf.pages, file_path, state)
    return state.transactions


def _run_business_on_pages(
    pages: List[Any],
    file_path: str,
    state: _BusinessParserState,
) -> None:
    """Business layout: narrative lines often precede the double-date amount line."""
    for page in pages:
        text = page.extract_text()
        if not text:
            page.flush_cache()
            continue

        lines = text.split("\n")
        # Split date blocks appear on every page; header "Transacti" / "on Date" may only be on page 1.
        lines = _normalize_equity_split_date_block_lines(lines)

        for line in lines:
            raw_line = line
            line = line.strip()
            if (
                "Narrative" in raw_line
                and "Debit" in raw_line
                and "Credit" in raw_line
                and "Running Balance" in raw_line
            ):
                state.seen_table = True
                state.buffer = []
                continue

            if not state.seen_table:
                continue

            if _DATE2_PAT.match(line) or _DATE1_BUS_PAT.match(line):
                prefix = " ".join(state.buffer).strip()
                state.buffer = []
                parsed, bal_update = _parse_business_txn_line(
                    line, prefix, state.previous_balance
                )
                if bal_update is not None:
                    state.previous_balance = bal_update
                if not parsed:
                    continue
                state.row_idx = _append_raw_transaction(
                    state.transactions, parsed, file_path, state.row_idx
                )
            elif line:
                state.buffer.append(line)
        page.flush_cache()


def _run_split_date_on_pages(
    pages: List[Any],
    file_path: str,
    state: _BusinessParserState,
) -> None:
    """
    Coordinate-based extractor for the April 2025 split-date layout.

    Equity's iText renderer splits Transaction Date across two text runs; pdfplumber
    line extraction drops many rows. This path uses word coordinates and appends
    RawTransaction rows like _run_business_on_pages.
    """
    for page in pages:
        words = page.extract_words()
        data = [w for w in words if w["top"] > _APR_DATA_TOP_MIN]

        date_prefixes = [
            w
            for w in data
            if _APR_DATE_X_MIN <= w["x0"] <= _APR_DATE_X_MAX
            and _APR_DATE_PREFIX_PAT.match(w["text"])
        ]
        year_words = [
            w
            for w in data
            if _APR_DATE_X_MIN <= w["x0"] <= _APR_DATE_X_MAX
            and _APR_YEAR_PAT.match(w["text"])
        ]

        for dp in date_prefixes:
            matched_years = [y for y in year_words if 5 <= y["top"] - dp["top"] <= 12]
            if not matched_years:
                logger.debug(
                    "split-date: no year for '%s' top=%.1f — skipped",
                    dp["text"],
                    dp["top"],
                )
                continue

            m = _APR_DATE_PREFIX_PAT.match(dp["text"])
            if not m:
                continue
            year = matched_years[0]["text"]
            # DD-MM-YYYY for _append_raw_transaction / _parse_equity_date
            date_raw_ddmmyyyy = f"{m.group(1)}-{m.group(2)}-{year}"

            row_top = dp["top"] + 4

            narr_words = [
                w
                for w in data
                if _APR_NARR_X_MIN <= w["x0"] < _APR_NARR_X_MAX
                and dp["top"] - 10 <= w["top"] <= dp["top"] + 28
            ]
            description = " ".join(
                w["text"] for w in sorted(narr_words, key=lambda w: (w["top"], w["x0"]))
            )

            amount_words = [
                w
                for w in data
                if _APR_DEBIT_X_MIN <= w["x0"] < _APR_BALANCE_X_MIN
                and abs(w["top"] - row_top) <= 6
                and _APR_AMOUNT_PREFIX_PAT.match(w["text"])
            ]
            debit_raw = None
            credit_raw = None
            for aw in amount_words:
                m = _APR_AMOUNT_PREFIX_PAT.match(aw["text"])
                amount_val = m.group(1) if m else aw["text"]
                if aw["x0"] < _APR_DEBIT_CREDIT_X:
                    debit_raw = amount_val
                else:
                    credit_raw = amount_val

            balance_words = [
                w
                for w in data
                if w["x0"] >= _APR_BALANCE_X_MIN
                and abs(w["top"] - row_top) <= 6
                and _APR_AMOUNT_PAT.match(w["text"].lstrip("-"))
            ]
            balance_raw = balance_words[0]["text"] if balance_words else None

            parsed = {
                "date_raw": date_raw_ddmmyyyy,
                "particulars": description.strip(),
                "money_out": debit_raw or "",
                "money_in": credit_raw or "",
                "balance_raw": balance_raw or "",
                "is_opening": False,
            }
            state.row_idx = _append_raw_transaction(
                state.transactions, parsed, file_path, state.row_idx
            )
        page.flush_cache()


def _extract_equity_business(pdf: Any, file_path: str) -> List[RawTransaction]:
    state = _BusinessParserState()
    _run_business_on_pages(pdf.pages, file_path, state)
    return state.transactions


def _finalize_equity_transactions(transactions: List[RawTransaction]) -> List[RawTransaction]:
    """Renumber row_index, drop exact duplicates (combined list, not per-chunk)."""
    seen: set[Tuple[str, str, str, str, str]] = set()
    deduped: List[RawTransaction] = []
    for t in transactions:
        fp = (
            t.date_raw or "",
            t.description or "",
            t.debit_raw or "",
            t.credit_raw or "",
            t.balance_raw or "",
        )
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(t)
    out: List[RawTransaction] = []
    for i, t in enumerate(deduped):
        d = t.model_dump()
        d["row_index"] = i
        out.append(RawTransaction(**d))
    return out


def extract_equity_pdf(file_path: str) -> ExtractionResult:
    warnings: List[WarningItem] = []
    transactions: List[RawTransaction] = []

    with pdfplumber.open(file_path) as pdf:
        page_count = len(pdf.pages)
        sample_parts: List[str] = []
        for i, page in enumerate(pdf.pages[:2]):
            t = page.extract_text()
            if t:
                sample_parts.append(t)
        sample = "\n".join(sample_parts)

        is_business = _is_equity_business_format(sample)

        first_page_lines = (pdf.pages[0].extract_text() or "").splitlines()
        split_date_layout = is_business and _is_split_date_layout(first_page_lines)
        if split_date_layout:
            logger.info("equity: split-date layout detected — using coordinate extractor")

        if page_count <= EQUITY_PAGE_CHUNK_SIZE:
            if is_business:
                if split_date_layout:
                    state_small = _BusinessParserState()
                    _run_split_date_on_pages(pdf.pages, file_path, state_small)
                    transactions = state_small.transactions
                else:
                    transactions = _extract_equity_business(pdf, file_path)
            else:
                transactions = _extract_equity_personal(pdf, file_path)
        else:
            num_chunks = (page_count + EQUITY_PAGE_CHUNK_SIZE - 1) // EQUITY_PAGE_CHUNK_SIZE
            logger.info(
                "Equity PDF chunking: total_pages=%d chunk_size=%d chunk_count=%d",
                page_count,
                EQUITY_PAGE_CHUNK_SIZE,
                num_chunks,
            )
            if is_business:
                state = _BusinessParserState()
                for chunk_i in range(num_chunks):
                    start = chunk_i * EQUITY_PAGE_CHUNK_SIZE
                    end = min(start + EQUITY_PAGE_CHUNK_SIZE, page_count)
                    chunk_pages = pdf.pages[start:end]
                    logger.info(
                        "Processing chunk %d/%d (pages %d-%d)",
                        chunk_i + 1,
                        num_chunks,
                        start + 1,
                        end,
                    )
                    before = len(state.transactions)
                    if split_date_layout:
                        _run_split_date_on_pages(chunk_pages, file_path, state)
                    else:
                        _run_business_on_pages(chunk_pages, file_path, state)
                    if len(state.transactions) == before and (end - start) > 2:
                        logger.warning(
                            "Equity chunk %d/%d produced 0 new transactions (pages %d-%d)",
                            chunk_i + 1,
                            num_chunks,
                            start + 1,
                            end,
                        )
                transactions = _finalize_equity_transactions(state.transactions)
            else:
                state = _PersonalParserState()
                for chunk_i in range(num_chunks):
                    start = chunk_i * EQUITY_PAGE_CHUNK_SIZE
                    end = min(start + EQUITY_PAGE_CHUNK_SIZE, page_count)
                    chunk_pages = pdf.pages[start:end]
                    logger.info(
                        "Processing chunk %d/%d (pages %d-%d)",
                        chunk_i + 1,
                        num_chunks,
                        start + 1,
                        end,
                    )
                    before = len(state.transactions)
                    _run_personal_on_pages(chunk_pages, file_path, state)
                    if len(state.transactions) == before and (end - start) > 2:
                        logger.warning(
                            "Equity chunk %d/%d produced 0 new transactions (pages %d-%d)",
                            chunk_i + 1,
                            num_chunks,
                            start + 1,
                            end,
                        )
                transactions = _finalize_equity_transactions(state.transactions)

        if len(transactions) == 0 and page_count > 5:
            sample_lines: List[str] = []
            for page in pdf.pages[:3]:
                t = page.extract_text() or ""
                sample_lines.extend(t.split("\n")[:10])
            preview = "\n".join(sample_lines[:10])
            logger.warning(
                "Equity extraction returned 0 transactions for %s (pages=%d). First lines of text:\n%s",
                file_path,
                page_count,
                preview,
            )

    return ExtractionResult(
        source_file=file_path,
        extractor_type="equity_pdf",
        row_count=len(transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=transactions,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Equity "F1" business account format (PAR-65)
# DD-MM-YYYY dates — line-based extraction, net-new (no prior detector/extractor)
#
# Columns: Tran Date | Value Date | Tran Particulars | Instrument Id | Debit |
# Credit | Balance. Header wraps "Instrument Id" across two lines ("Instrument"
# on the header row, "Id" alone on the next).
#
# Naming caveat (unresolved as of PAR-65): the source filename and backlog
# ticket call this "F1", but the statement's own "Product Name" field reads
# "CAA" — "F1" does not appear anywhere in the document text. The functions
# below use "f1" purely as the working name from the ticket/filename; this is
# NOT a claim that the document self-identifies as F1. See
# tests/fixtures/real_samples/manifest.json's entry for this fixture and
# rust_engine_prototype/CLAUDE_CODE_INSTRUCTIONS.md Task 3 for the same
# open question.
#
# Structurally distinct from the existing "business" layout above: here, each
# transaction's Instrument Id + counterparty name print as continuation
# line(s) AFTER the date/amount line (belonging to that same row), not before
# it as a narrative prefix to the next row.
# ─────────────────────────────────────────────────────────────────────────────

_F1_PAGE_NUM_PAT = re.compile(r"^\d+\s*/\s*\d+$")
# Negative-aware, unlike the shared _AMOUNT_PAT: F1 statements print momentary
# overdrafts as a signed running balance ("-99,707.40"), not a "Dr" suffix.
_F1_AMOUNT_PAT = re.compile(r"-?[\d,]+\.\d{2}")


def _f1_parse_amounts_from_rest(
    rest: str, previous_balance: Optional[int] = None
) -> Tuple[Optional[int], Optional[int], Optional[int], List[str]]:
    """Like _parse_equity_business_amounts_from_rest, but balance-sign-aware."""
    matches = _F1_AMOUNT_PAT.findall(rest)
    if not matches:
        return None, None, None, matches

    amounts_cents = [_amount_str_to_cents(m) for m in matches]

    if len(amounts_cents) == 1:
        return None, None, amounts_cents[0], matches

    if len(amounts_cents) == 2:
        amount, balance = amounts_cents[0], amounts_cents[1]
        if previous_balance is not None:
            if balance < previous_balance:
                return amount, None, balance, matches
            if balance > previous_balance:
                return None, amount, balance, matches
            return None, None, balance, matches
        return amount, None, balance, matches

    if len(amounts_cents) == 3:
        return amounts_cents[0], amounts_cents[1], amounts_cents[2], matches

    return amounts_cents[-3], amounts_cents[-2], amounts_cents[-1], matches


def _is_equity_f1_business_format(text: str) -> bool:
    """Structural signature: Account Statement + Tran Particulars/Instrument
    columns, distinct from the "Narrative"/"Running Balance" business layout.

    Note: the document's own Product Name field prints "CAA" — that is the
    authoritative label for this account type.  "F1" is GBFund's colloquial
    alias (from the original request/filename) and does NOT appear in the
    document text.  We match structural column headers rather than either
    label so the signature is robust to both names.  Search for "F1" to find
    the functions; search for "CAA" to find this note.
    """
    return (
        "Account Statement" in text
        and "Tran Particulars" in text
        and "Instrument" in text
        and "Debit" in text
        and "Credit" in text
    )


def detect_equity_f1(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF matches the Equity CAA business account layout.

    The document's Product Name field reads "CAA" — that is the authoritative
    name printed on the statement.  "F1" is GBFund's internal alias for the
    same format and does not appear in document text; functions retain the f1
    suffix as the working name from ticket PAR-65 / the source filename.
    """
    try:
        with as_document(source) as doc:
            text = doc.text_upto(2)
            return _is_equity_f1_business_format(text)
    except Exception:
        return False


def _is_f1_noise_line(line: str) -> bool:
    """Lines that are page furniture, not transaction content or continuation text."""
    if not line or line == "_" or line == "Id":
        return True
    if line.startswith("HEAD OFFICE"):
        return True
    if line.startswith("Account No.") or line.startswith("Customer Name"):
        return True
    if _F1_PAGE_NUM_PAT.match(line):
        return True
    if line.upper().startswith("NOTE: ANY OMISSION"):
        return True
    if "GRAND TOTAL" in line.upper():
        return True
    if line.startswith("Tran Date") and "Tran Particulars" in line:
        return True
    return False


class _F1ParserState:
    __slots__ = (
        "seen_table",
        "table_ended",
        "previous_balance",
        "pending",
        "row_idx",
        "transactions",
    )

    def __init__(self) -> None:
        self.seen_table = False
        self.table_ended = False
        self.previous_balance: Optional[int] = None
        self.pending: Optional[dict] = None
        self.row_idx = 0
        self.transactions: List[RawTransaction] = []


def _flush_f1_pending(state: _F1ParserState, file_path: str) -> None:
    if state.pending is None:
        return
    p = state.pending
    parsed = {
        "date_raw": p["date_raw"],
        "particulars": re.sub(r"\s+", " ", p["particulars"]).strip(),
        "money_out": _cents_to_equity_raw(p["debit_cents"]) if p["debit_cents"] else "",
        "money_in": _cents_to_equity_raw(p["credit_cents"]) if p["credit_cents"] else "",
        "balance_raw": (
            _cents_to_equity_raw(p["balance_cents"]) if p["balance_cents"] is not None else ""
        ),
        "is_opening": False,
    }
    state.row_idx = _append_raw_transaction(state.transactions, parsed, file_path, state.row_idx)
    state.pending = None


def _run_f1_on_pages(pages: List[Any], file_path: str, state: _F1ParserState) -> None:
    for page in pages:
        text = page.extract_text()
        if not text:
            page.flush_cache()
            continue

        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if state.table_ended:
                continue
            if not state.seen_table:
                if "Tran Date" in raw_line and "Tran Particulars" in raw_line:
                    state.seen_table = True
                continue

            if "GRAND TOTAL" in line.upper():
                # Everything after the closing recap (page signature/stamp
                # lines like "END" + a trailer code) is not transaction data.
                _flush_f1_pending(state, file_path)
                state.table_ended = True
                continue

            if _is_f1_noise_line(line):
                continue

            m = _DATE2_PAT.match(line)
            if m:
                _flush_f1_pending(state, file_path)
                rest = m.group(3).strip()
                is_first_txn = state.previous_balance is None
                debit, credit, balance, amounts = _f1_parse_amounts_from_rest(
                    rest, state.previous_balance
                )
                particulars = _strip_amounts_from_rest(rest, amounts)
                if (
                    is_first_txn
                    and debit is not None
                    and credit is None
                    and particulars.startswith("MPS")
                ):
                    # No opening-balance row precedes the very first transaction,
                    # so its direction can't be read off a balance delta like every
                    # other row. Every other "MPS <phone> ... <name>" row in this
                    # statement (679/680, verified against the statement's own
                    # Grand Total recap) is a mobile-money inbound credit, so the
                    # shared helper's no-prior-balance debit default is wrong here.
                    debit, credit = None, debit
                if balance is not None:
                    state.previous_balance = balance
                state.pending = {
                    "date_raw": m.group(1),
                    "particulars": particulars,
                    "debit_cents": debit,
                    "credit_cents": credit,
                    "balance_cents": balance,
                }
            elif line and state.pending is not None:
                state.pending["particulars"] = (
                    f"{state.pending['particulars']} {line}".strip()
                )
        page.flush_cache()


def extract_equity_f1_pdf(file_path: str) -> ExtractionResult:
    warnings: List[WarningItem] = []
    state = _F1ParserState()

    with pdfplumber.open(file_path) as pdf:
        _run_f1_on_pages(pdf.pages, file_path, state)
        _flush_f1_pending(state, file_path)

    return ExtractionResult(
        source_file=file_path,
        extractor_type="equity_pdf",
        row_count=len(state.transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=state.transactions,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Equity CLMS (Cash and Liquidity Management System) format
# DD/MM/YYYY dates — coordinate-based extraction
# ─────────────────────────────────────────────────────────────────────────────

_EQ_CLMS_DATE_PAT = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_EQ_CLMS_AMOUNT_PAT = re.compile(r"^[\d,]+\.\d{2}$")

# X-thresholds measured from Buildex Equity CLMS statement (768pt wide page)
_EQ_CLMS_TXN_DATE_X_MIN = 30.0
_EQ_CLMS_TXN_DATE_X_MAX = 92.0
_EQ_CLMS_DESC_X_MIN = 145.0
_EQ_CLMS_DESC_X_MAX = 430.0
_EQ_CLMS_CREDIT_X_MIN = 460.0   # credit amount left edge
_EQ_CLMS_BALANCE_X_MIN = 520.0  # balance amount left edge
_EQ_CLMS_ROW_TOLERANCE = 3.5
_EQ_CLMS_DESC_ABOVE_MAX = 22.0


def detect_equity_clms(source: Union[str, NormalizedDocument]) -> bool:
    """Return True if the PDF is an Equity CLMS (Cash and Liquidity Mgmt System) statement.

    Distinct from the standard business format: header includes
    "EQUITY BANK ACCOUNT FOR CASH AND LIQUIDITY MGT SYSTEM" and uses
    DD/MM/YYYY dates instead of DD-MM-YYYY.
    """
    try:
        with as_document(source) as doc:
            if not doc.pages:
                return False
            text = doc.pages[0].text
            return (
                "CASH AND LIQUIDITY" in text.upper()
                and "Total Count:" in text
                and bool(re.search(r"\d{2}/\d{2}/\d{4}", text))
            )
    except Exception:
        return False


def _parse_equity_clms_date(s: str) -> Optional[str]:
    """Parse DD/MM/YYYY to ISO YYYY-MM-DD."""
    try:
        dt = datetime.strptime(s.strip(), "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _clean_clms_amount(raw: str) -> str:
    """Strip commas; return '' for zero or missing amounts."""
    if not raw:
        return ""
    cleaned = raw.replace(",", "").strip()
    if cleaned in ("0.00", "0", ""):
        return ""
    return cleaned


def extract_equity_clms_pdf(source: Union[str, NormalizedDocument]) -> ExtractionResult:
    """Extract transactions from an Equity CLMS PDF statement.

    Uses coordinate-based word extraction.  Description words at
    x0 145–430 (TxnRef + Narrative + CustomerRef columns) are assigned
    to the nearest date-anchor row within ±22 px.

    Amount zones (right-aligned text):
      debit:   x0 < 460
      credit:  460 ≤ x0 < 520
      balance: x0 ≥ 520

    `source` may be a raw path or an already-parsed `NormalizedDocument`
    (PAR-216) -- when the router already parsed the file once for format
    detection, reusing that same parse here (rather than a second
    independent `pdfplumber.open()`) roughly halves both wall time and
    peak memory on large statements. This was the actual root cause of a
    real production OOM on a 451-page Equity CLMS file (2Gi container
    limit, ~2076 MiB used) -- the file was being fully parsed twice.
    """
    transactions: List[RawTransaction] = []
    warnings: List[WarningItem] = []

    with as_document(source) as doc:
        file_path = doc.file_path
        for page in doc.pages:
            words = page.words
            if not words:
                page.flush_cache()
                continue

            words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))

            # ── Anchor rows: first occurrence of DD/MM/YYYY in TXN_DATE zone ──
            anchor_tops = [
                w["top"]
                for w in words_sorted
                if _EQ_CLMS_TXN_DATE_X_MIN <= w["x0"] <= _EQ_CLMS_TXN_DATE_X_MAX
                and _EQ_CLMS_DATE_PAT.match(w["text"])
            ]
            if not anchor_tops:
                continue

            # ── Per-anchor: collect amounts and inline description ─────────────
            anchors = []
            for at in anchor_tops:
                row_words = [
                    w for w in words_sorted
                    if abs(w["top"] - at) <= _EQ_CLMS_ROW_TOLERANCE
                ]
                date_words = [
                    w for w in row_words
                    if _EQ_CLMS_TXN_DATE_X_MIN <= w["x0"] <= _EQ_CLMS_TXN_DATE_X_MAX
                    and _EQ_CLMS_DATE_PAT.match(w["text"])
                ]
                if not date_words:
                    continue

                debit = credit = balance = ""
                inline_desc: List[dict] = []

                for w in row_words:
                    x0, text = w["x0"], w["text"]
                    is_amount = bool(_EQ_CLMS_AMOUNT_PAT.match(text))
                    if is_amount:
                        if x0 >= _EQ_CLMS_BALANCE_X_MIN:
                            balance = text
                        elif x0 >= _EQ_CLMS_CREDIT_X_MIN:
                            credit = text
                        else:
                            debit = text
                    elif _EQ_CLMS_DESC_X_MIN <= x0 <= _EQ_CLMS_DESC_X_MAX:
                        inline_desc.append(w)

                anchors.append({
                    "top": at,
                    "date_raw": _parse_equity_clms_date(date_words[0]["text"]) or "",
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "inline_desc": inline_desc,
                    "extra_desc": [],
                })

            # ── Assign floating description words to nearest anchor ────────────
            for w in words_sorted:
                x0, top, text = w["x0"], w["top"], w["text"]
                if not (_EQ_CLMS_DESC_X_MIN <= x0 <= _EQ_CLMS_DESC_X_MAX):
                    continue
                if _EQ_CLMS_DATE_PAT.match(text) or _EQ_CLMS_AMOUNT_PAT.match(text):
                    continue
                if any(abs(a["top"] - top) <= _EQ_CLMS_ROW_TOLERANCE for a in anchors):
                    continue  # already captured as inline_desc

                nearest = min(anchors, key=lambda a: abs(a["top"] - top))
                if nearest["top"] - top > _EQ_CLMS_DESC_ABOVE_MAX:
                    continue  # header artifact
                nearest["extra_desc"].append(w)

            # ── Build transactions ─────────────────────────────────────────────
            for anchor in anchors:
                all_desc = sorted(
                    anchor["extra_desc"] + anchor["inline_desc"],
                    key=lambda w: (w["top"], w["x0"]),
                )
                description = " ".join(w["text"] for w in all_desc).strip()
                is_b_fwd = "B/FWD" in description.upper() or "BALANCE B/FWD" in description.upper()

                transactions.append(
                    RawTransaction(
                        row_index=len(transactions),
                        date_raw=anchor["date_raw"],
                        description=description,
                        debit_raw="" if is_b_fwd else _clean_clms_amount(anchor["debit"]),
                        credit_raw="" if is_b_fwd else _clean_clms_amount(anchor["credit"]),
                        balance_raw=anchor["balance"].replace(",", "") if anchor["balance"] else "",
                        source_file=file_path,
                        extraction_confidence=1.0,
                    )
                )

            page.flush_cache()

    return ExtractionResult(
        source_file=file_path,
        extractor_type="equity_pdf",
        row_count=len(transactions),
        extraction_status="success",
        warnings=warnings,
        raw_transactions=transactions,
    )
