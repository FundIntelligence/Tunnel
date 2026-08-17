"""
Audited Financial Statements PDF Extractor.

Handles the "character soup" PDF layout produced by many Kenyan accounting
software tools (QuickBooks, Sage, etc.) where every glyph is a separate
PDF text object.  The strategy:

  1. Extract words at tight tolerances (x_tol=2, y_tol=1) to preserve
     individual character positions.
  2. Group characters into logical rows using an interval-merge (tol=2 px).
  3. Within each row, partition by x-zone into: label | note# | value | prior-value.
  4. Reconstruct text by sorting and concatenating chars within each zone.
  5. Match reconstructed labels to known line items via keyword patterns.

Tested on: Buildex Interiors Company Ltd FY2025 (24-page PDF).
"""
from __future__ import annotations

import gc
import hashlib
import logging
import re
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

from app.extractors.currency_detector import detect as detect_currency

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# COLUMN ZONE DEFINITIONS  (x0 boundaries per page type)
# ─────────────────────────────────────────────────────────────────────────────

# Income Statement  (page heading: STATEMENT OF COMPREHENSIVE INCOME)
_IS = dict(label_max=270, note_max=340, cur_min=340, cur_max=440, pri_min=440)

# Balance Sheet  (page heading: STATEMENT OF FINANCIAL POSITION)
_BS = dict(label_max=250, note_max=290, cur_min=290, cur_max=360, pri_min=360)

# Cash Flow  (page heading: CASHFLOW STATEMENT)
_CF = dict(label_max=370, note_max=380, cur_min=370, cur_max=445, pri_min=445)

# Notes pages  (Note 11 cash, Note 14 loans) — same layout as BS but wider labels
_NT = dict(label_max=355, note_max=360, cur_min=355, cur_max=425, pri_min=425)


# ─────────────────────────────────────────────────────────────────────────────
# ROW RECONSTRUCTION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _group_rows(words: List[dict], tol: int = 2) -> Dict[float, List[dict]]:
    """Merge character-level words into logical rows using interval merging."""
    if not words:
        return {}
    by_top = sorted(words, key=lambda w: w["top"])
    groups: Dict[float, List[dict]] = {}
    current_key: Optional[float] = None
    for w in by_top:
        if current_key is None or abs(w["top"] - current_key) > tol:
            current_key = w["top"]
        if current_key not in groups:
            groups[current_key] = []
        groups[current_key].append(w)
    return groups


def _zone_text(row_words: List[dict], x_min: float, x_max: float) -> str:
    """Concatenate text of words whose x0 falls within [x_min, x_max)."""
    chars = [w for w in row_words if x_min <= w["x0"] < x_max]
    return "".join(w["text"] for w in sorted(chars, key=lambda w: w["x0"])).strip()


def _parse_amount(raw: str) -> Optional[int]:
    """
    Convert a KES amount string to integer cents.

    Examples:
        "372,062,277"  → 37_206_227_700
        "(2,882,520)"  → -288_252_000
        "-"            → None (missing / not applicable)
        ""             → None
    """
    raw = raw.strip()
    if not raw or raw in ("-", "—", "nil", "Nil"):
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[(),\s]", "", raw)
    try:
        kes = int(cleaned)
    except ValueError:
        return None
    cents = kes * 100
    return -cents if negative else cents


# ─────────────────────────────────────────────────────────────────────────────
# PAGE FINDERS
# ─────────────────────────────────────────────────────────────────────────────

def _find_page(
    pdf,
    keywords: List[str],
    num_zone: Optional[Tuple[float, float, int]] = None,
) -> Optional[Any]:
    """
    Return the first page whose text contains ALL keywords (case-insensitive)
    AND, if num_zone=(x_min, x_max, min_count) is given, has at least
    min_count numeric characters in that x-range.

    This prevents false matches on auditor-report pages that *mention* a
    statement name in prose but contain no tabular data.
    """
    for page in pdf.pages:
        text = (page.extract_text() or "").upper()
        if not all(kw.upper() in text for kw in keywords):
            continue
        if num_zone is not None:
            x_min, x_max, min_count = num_zone
            words = page.extract_words(x_tolerance=2, y_tolerance=1)
            n = sum(
                1
                for w in words
                if x_min <= w["x0"] <= x_max and any(c.isdigit() for c in w["text"])
            )
            if n < min_count:
                continue
        return page
    return None


def _page_rows(page) -> Dict[float, List[dict]]:
    words = page.extract_words(x_tolerance=2, y_tolerance=1)
    return _group_rows(words, tol=2)


# ─────────────────────────────────────────────────────────────────────────────
# INCOME STATEMENT
# ─────────────────────────────────────────────────────────────────────────────

_IS_MAP = [
    ("turnover_cents",              ["turnover", "revenue", "sales income"]),
    ("other_income_cents",          ["other income", "other revenue"]),
    ("cost_of_sales_cents",         ["cost of sales", "cost of goods"]),
    ("operating_costs_cents",       ["operating cost"]),
    ("administrative_costs_cents",  ["administrative", "admin cost"]),
    ("staff_costs_cents",           ["staff cost", "employee cost", "payroll"]),
    ("finance_costs_cents",         ["finance cost", "interest", "bank charge"]),
    ("depreciation_expense_cents",  ["depreciation"]),
    ("profit_before_tax_cents",     ["profit before tax", "pbt", "loss before tax"]),
    ("tax_expense_cents",           ["tax expense", "taxation", "income tax"]),
    ("profit_after_tax_cents",      ["profit after tax", "pat", "net profit", "net income"]),
]


def _match_label(label: str, patterns: List[str]) -> bool:
    """
    Match a reconstructed label against keyword patterns.

    In character-soup PDFs every glyph is a separate text object, so
    `_zone_text` concatenates them *without* spaces.  We therefore strip
    spaces from both the label and the pattern before comparing.
    """
    label_lc = label.lower().replace(" ", "")
    return any(p.replace(" ", "") in label_lc for p in patterns)


def _extract_income_statement(pdf) -> Dict[str, int]:
    # num_zone: current-year column is x0 ≈ 350–440; require ≥15 numeric chars
    page = _find_page(pdf, ["COMPREHENSIVE INCOME"], num_zone=(350, 440, 15))
    if page is None:
        page = _find_page(pdf, ["PROFIT", "LOSS", "STATEMENT"], num_zone=(350, 440, 15))
    if page is None:
        raise ValueError("Income statement page not found")

    rows = _page_rows(page)
    data: Dict[str, Any] = {}

    for _top, row_words in sorted(rows.items()):
        label = _zone_text(row_words, 0, _IS["label_max"])
        if not label:
            continue
        cur_raw = _zone_text(row_words, _IS["cur_min"], _IS["cur_max"])
        if not cur_raw:
            continue
        amount = _parse_amount(cur_raw)
        if amount is None:
            continue

        for field, patterns in _IS_MAP:
            if field not in data and _match_label(label, patterns):
                # Cost / expense fields should be stored as positive cents
                if field in ("cost_of_sales_cents", "operating_costs_cents",
                             "administrative_costs_cents", "staff_costs_cents",
                             "finance_costs_cents", "depreciation_expense_cents",
                             "tax_expense_cents"):
                    data[field] = abs(amount)
                else:
                    data[field] = amount
                break

    data.setdefault("other_income_cents", 0)
    data.setdefault("depreciation_expense_cents", 0)
    data.setdefault("other_expenses_cents", 0)

    required = [
        "turnover_cents", "cost_of_sales_cents", "operating_costs_cents",
        "administrative_costs_cents", "staff_costs_cents", "finance_costs_cents",
        "profit_before_tax_cents", "tax_expense_cents", "profit_after_tax_cents",
    ]
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"Income statement — missing fields: {missing}")

    return data


# ─────────────────────────────────────────────────────────────────────────────
# BALANCE SHEET
# ─────────────────────────────────────────────────────────────────────────────

_BS_MAP = [
    ("property_plant_equipment_cents", ["property", "plant", "ppe"]),
    ("investments_cents",              ["investment"]),
    ("inventory_cents",                ["inventory", "stock"]),
    ("cash_and_equivalents_cents",     ["cash", "equivalent"]),
    ("trade_receivables_cents",        ["receivable", "debtor"]),
    ("total_assets_cents",             ["total asset"]),
    ("trade_payables_cents",           ["payable", "creditor"]),
    ("tax_payable_cents",              ["tax payable", "tax liab"]),
    ("long_term_loans_cents",          ["bank loan", "borrowing", "loan"]),
    ("retained_earnings_cents",        ["retained earning", "retained profit"]),
    ("share_capital_cents",            ["share capital"]),
    ("total_equity_and_liabilities_cents", ["total equity and liab", "total liab"]),
]

# Avoid mis-mapping "Total assets" row as a BS asset component
_BS_SKIP = {"total assets": "total_assets_cents"}


def _extract_balance_sheet(pdf) -> Dict[str, int]:
    # num_zone: current-year column is x0 ≈ 290–370; require ≥15 numeric chars
    page = _find_page(pdf, ["FINANCIAL POSITION"], num_zone=(290, 370, 15))
    if page is None:
        page = _find_page(pdf, ["BALANCE SHEET"], num_zone=(290, 370, 15))
    if page is None:
        raise ValueError("Balance sheet page not found")

    rows = _page_rows(page)
    data: Dict[str, Any] = {}

    for _top, row_words in sorted(rows.items()):
        label = _zone_text(row_words, 0, _BS["label_max"])
        if not label:
            continue
        cur_raw = _zone_text(row_words, _BS["cur_min"], _BS["cur_max"])
        if not cur_raw:
            continue
        amount = _parse_amount(cur_raw)
        if amount is None:
            continue

        for field, patterns in _BS_MAP:
            if field not in data and _match_label(label, patterns):
                data[field] = abs(amount)
                break

    # Defaults for optional fields
    data.setdefault("intangible_assets_cents", 0)
    data.setdefault("investments_cents", 0)
    data.setdefault("other_receivables_cents", 0)
    data.setdefault("prepayments_cents", 0)
    data.setdefault("tax_payable_cents", 0)
    data.setdefault("short_term_loans_cents", 0)
    data.setdefault("other_payables_cents", 0)
    data.setdefault("other_noncurrent_liabilities_cents", 0)
    data.setdefault("other_reserves_cents", 0)

    required = [
        "property_plant_equipment_cents", "inventory_cents",
        "cash_and_equivalents_cents", "trade_receivables_cents",
        "trade_payables_cents", "long_term_loans_cents",
        "share_capital_cents", "retained_earnings_cents",
    ]
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"Balance sheet — missing fields: {missing}")

    return data


# ─────────────────────────────────────────────────────────────────────────────
# CASH FLOW STATEMENT
# ─────────────────────────────────────────────────────────────────────────────

_CF_MAP = [
    ("operating_cashflow_cents",  ["net cash from operating", "net cashflow from operating",
                                    "net cash used in operating"]),
    ("investing_cashflow_cents",  ["net cash", "investing activit", "net cashflow used in investing"]),
    ("financing_cashflow_cents",  ["net cash", "financing activit", "net cashflow from financing",
                                    "net cashflow used in financing"]),
    ("cash_at_start_cents",       ["cash", "start of year", "beginning of year", "start of period"]),
    ("cash_at_end_cents",         ["cash", "end of year", "end of period", "close"]),
]

# Operating / investing / financing headings appear as section starters.
# We match by presence of "operating", "investing", "financing" together with "net"
_CF_SECTION_PATTERNS = [
    ("operating_cashflow_cents",  ["net cash", "operating"]),
    ("investing_cashflow_cents",  ["net cash", "investing"]),
    ("financing_cashflow_cents",  ["net cash", "financing"]),
    ("cash_at_start_cents",       ["cash", "start"]),
    ("cash_at_end_cents",         ["cash", "end"]),
]


def _extract_cashflow(pdf) -> Dict[str, int]:
    # num_zone: current-year column is x0 ≈ 370–450; require ≥15 numeric chars
    page = _find_page(pdf, ["CASHFLOW"], num_zone=(370, 450, 15))
    if page is None:
        page = _find_page(pdf, ["CASH FLOW"], num_zone=(370, 450, 15))
    if page is None:
        raise ValueError("Cash flow statement page not found")

    rows = _page_rows(page)
    data: Dict[str, Any] = {}

    for _top, row_words in sorted(rows.items()):
        label = _zone_text(row_words, 0, _CF["label_max"])
        if not label:
            continue
        cur_raw = _zone_text(row_words, _CF["cur_min"], _CF["cur_max"])
        if not cur_raw:
            continue
        amount = _parse_amount(cur_raw)
        if amount is None:
            continue

        # Strip spaces in both label and patterns (character-soup PDFs
        # concatenate glyphs without space characters).
        label_lc = label.lower().replace(" ", "")
        for field, patterns in _CF_SECTION_PATTERNS:
            if field not in data and all(
                p.replace(" ", "") in label_lc for p in patterns
            ):
                data[field] = amount
                break

    required = [
        "operating_cashflow_cents", "investing_cashflow_cents",
        "financing_cashflow_cents", "cash_at_start_cents", "cash_at_end_cents",
    ]
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"Cash flow statement — missing fields: {missing}")

    return data


# ─────────────────────────────────────────────────────────────────────────────
# NOTES  (Note 11: cash breakdown, Note 14: loan breakdown)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_notes(pdf) -> Dict[str, Any]:
    """
    Extract Note 11 (cash breakdown) and Note 14 (loan breakdown).

    Detection uses word-coordinate reconstruction rather than extract_text(),
    because character-soup PDFs produce scrambled text from extract_text().
    """
    # Notes page x-zones (derived from page 22 coordinate inspection)
    # Labels: x0 < 285; current year: x0 353–420; prior year: x0 441–510
    _N_LABEL_MAX = 285
    _N_CUR_MIN   = 353
    _N_CUR_MAX   = 420
    _N_PRI_MIN   = 441

    cash_breakdown: Dict[str, int] = {}
    loan_breakdown: List[Dict[str, Any]] = []

    for page in pdf.pages:
        rows = _page_rows(page)

        in_cash_note = False
        in_loan_note = False

        for _top, row_words in sorted(rows.items()):
            # Use a wider label zone to reconstruct note header text
            label_raw = _zone_text(row_words, 0, _N_LABEL_MAX)
            label_lc  = label_raw.lower().replace(" ", "")

            # ── Note 11 header ─────────────────────────────────────────────
            # On the notes page, note number is the leftmost token ("11" prefix).
            # On the balance sheet, "Cash&CashEquivalents11" has "11" as suffix.
            # We only want the notes page, so require the label to START with "11".
            if label_raw.strip().startswith("11") and "cash" in label_lc and "equivalent" in label_lc:
                in_cash_note = True
                in_loan_note = False
                continue

            # ── Note 14 header ─────────────────────────────────────────────
            # Same logic: require label to start with "14"
            if label_raw.strip().startswith("14") and ("bankloan" in label_lc or "loan" in label_lc):
                in_loan_note = True
                in_cash_note = False
                continue

            # ── Stop at any subsequent note header (12/13/15…) ─────────────
            if in_cash_note or in_loan_note:
                # A note header looks like "12Something" or "15Something"
                m = re.match(r"^1[2-9]([A-Za-z]|$)", label_raw.strip())
                if m:
                    if in_cash_note and "14" not in label_raw:
                        in_cash_note = False
                    if in_loan_note:
                        in_loan_note = False

            cur_raw = _zone_text(row_words, _N_CUR_MIN, _N_CUR_MAX)
            amount  = _parse_amount(cur_raw)

            # ── Cash items ─────────────────────────────────────────────────
            if in_cash_note and amount is not None and amount > 0:
                if not label_lc or label_lc.startswith("total"):
                    continue

                # Map to canonical bank name
                if "absa" in label_lc or label_lc.startswith("abs"):
                    key = "Absa"
                elif "equity" in label_lc:
                    key = "Equity"
                elif "kcb" in label_lc:
                    key = "KCB"
                elif "zemo" in label_lc:
                    key = "Zemo"
                elif "tendepay" in label_lc or "tenderpay" in label_lc or "tender" in label_lc:
                    key = "Tendepay"
                else:
                    key = label_raw.strip()[:40]

                if key:
                    cash_breakdown[key] = cash_breakdown.get(key, 0) + amount

            # ── Loan items ─────────────────────────────────────────────────
            if in_loan_note and amount is not None and amount > 0:
                if not label_lc or label_lc.startswith("total"):
                    continue

                # Accept any row that looks like a facility name
                if any(
                    k in label_lc
                    for k in ("assetfinance", "loan", "facility",
                              "overdraft", "mortgage", "jiinue", "jiine",
                              "normal", "absa")
                ):
                    loan_breakdown.append({
                        "name": label_raw.strip()[:80],
                        "amount_cents": amount,
                    })

    return {
        "cash_breakdown": cash_breakdown if cash_breakdown else None,
        "loan_breakdown": loan_breakdown if loan_breakdown else None,
        "fixed_assets_detail": None,
        "other_notes": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# METADATA
# ─────────────────────────────────────────────────────────────────────────────

def _extract_metadata(pdf) -> Dict[str, Any]:
    raw_text = pdf.pages[0].extract_text() or ""
    text = raw_text.upper()

    # Company name — first ALL-CAPS line that contains "LIMITED" or "LTD"
    company_name = "Unknown Company"
    for line in text.splitlines():
        line = line.strip()
        if re.search(r"\bLIMITED\b|\bLTD\b", line) and len(line) > 5:
            company_name = line
            break

    # Financial year — "YEAR ENDED DD MONTH YYYY"
    year_match = re.search(
        r"YEAR\s+ENDED\s+(\d{1,2})\s+(\w+)\s+(\d{4})", text
    )
    if year_match:
        try:
            from datetime import datetime as _dt
            d, m, y = year_match.groups()
            financial_year = int(y)
            financial_year_end = _dt.strptime(f"{d} {m} {y}", "%d %B %Y").date()
        except ValueError:
            financial_year = int(year_match.group(3))
            financial_year_end = None
    else:
        # Fallback: grab any 4-digit year
        ym = re.search(r"20\d{2}", text)
        financial_year = int(ym.group()) if ym else 2025
        financial_year_end = None

    from datetime import date as _date
    if financial_year_end is None:
        financial_year_end = _date(financial_year, 12, 31)

    # Currency: the cover page rarely states it — audited financial statements
    # typically declare it in a later accounting-policy note ("Basis of
    # preparation") or an explicit currency note, not on page 1. Fall through to
    # the rest of the document, page by page, stopping at the first hit.
    currency = detect_currency(raw_text)
    if currency is None:
        for page in pdf.pages[1:]:
            currency = detect_currency(page.extract_text() or "")
            if currency:
                break

    return {
        "company_name": company_name,
        "financial_year": financial_year,
        "financial_year_start": _date(financial_year, 1, 1).isoformat(),
        "financial_year_end": financial_year_end.isoformat(),
        "currency": currency,
        "auditor_name": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION & CONFIDENCE
# ─────────────────────────────────────────────────────────────────────────────

def _calculate_confidence(data: Dict[str, Any]) -> Decimal:
    checks_passed = 0
    total_checks = 5

    # 1. All 9 income statement fields present
    is_fields = ["turnover_cents", "cost_of_sales_cents", "profit_before_tax_cents",
                 "tax_expense_cents", "profit_after_tax_cents"]
    if all(f in data for f in is_fields):
        checks_passed += 1

    # 2. All 8 balance sheet fields present
    bs_fields = ["property_plant_equipment_cents", "inventory_cents",
                 "cash_and_equivalents_cents", "trade_payables_cents"]
    if all(f in data for f in bs_fields):
        checks_passed += 1

    # 3. PAT = PBT - Tax (within KES 1 rounding tolerance)
    if all(f in data for f in ["profit_before_tax_cents", "tax_expense_cents",
                                "profit_after_tax_cents"]):
        expected = data["profit_before_tax_cents"] - data["tax_expense_cents"]
        if abs(expected - data["profit_after_tax_cents"]) <= 100:
            checks_passed += 1

    # 4. Cash flow reconciles: net activities = end - start (1% tolerance)
    cf_keys = ["operating_cashflow_cents", "investing_cashflow_cents",
               "financing_cashflow_cents", "cash_at_start_cents", "cash_at_end_cents"]
    if all(f in data for f in cf_keys):
        net_act = (data["operating_cashflow_cents"] +
                   data["investing_cashflow_cents"] +
                   data["financing_cashflow_cents"])
        net_bal = data["cash_at_end_cents"] - data["cash_at_start_cents"]
        tol = max(abs(net_bal) * Decimal("0.01"), 100)
        if abs(net_act - net_bal) <= tol:
            checks_passed += 1

    # 5. Cash breakdown total matches balance sheet cash (if both present)
    if data.get("cash_breakdown") and data.get("cash_and_equivalents_cents"):
        breakdown_total = sum(data["cash_breakdown"].values())
        bs_cash = data["cash_and_equivalents_cents"]
        if abs(breakdown_total - bs_cash) <= 100:
            checks_passed += 1
        # Still award partial if within 5%
        elif abs(breakdown_total - bs_cash) <= bs_cash * 0.05:
            checks_passed += 0.5

    return Decimal(str(round(checks_passed / total_checks * 100, 2)))


def _validate(data: Dict[str, Any]) -> None:
    """Raise ValueError on hard integrity failures."""
    # PAT = PBT - Tax
    if all(f in data for f in ["profit_before_tax_cents", "tax_expense_cents",
                                "profit_after_tax_cents"]):
        expected = data["profit_before_tax_cents"] - data["tax_expense_cents"]
        if abs(expected - data["profit_after_tax_cents"]) > 200:
            raise ValueError(
                f"PAT mismatch: PBT {data['profit_before_tax_cents']} - "
                f"Tax {data['tax_expense_cents']} = {expected} "
                f"≠ declared {data['profit_after_tax_cents']}"
            )

    # Cash flow: net activities ≈ end - start (allow 2%)
    cf_keys = ["operating_cashflow_cents", "investing_cashflow_cents",
               "financing_cashflow_cents", "cash_at_start_cents", "cash_at_end_cents"]
    if all(f in data for f in cf_keys):
        net_act = (data["operating_cashflow_cents"] +
                   data["investing_cashflow_cents"] +
                   data["financing_cashflow_cents"])
        net_bal = data["cash_at_end_cents"] - data["cash_at_start_cents"]
        tol = max(abs(net_bal) * 0.02, 200)
        if abs(net_act - net_bal) > tol:
            logger.warning(
                "Cash flow reconciliation gap: activities=%d balances=%d diff=%d",
                net_act, net_bal, net_act - net_bal,
            )


def _sha256(data: Dict[str, Any]) -> str:
    key = (
        f"{data.get('company_name')}|{data.get('financial_year')}|"
        f"{data.get('turnover_cents')}|{data.get('profit_after_tax_cents')}|"
        f"{data.get('cash_and_equivalents_cents')}"
    )
    return hashlib.sha256(key.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def extract_audited_financials(pdf_path: str) -> Dict[str, Any]:
    """
    Extract structured financial data from an audited financial statements PDF.

    Returns a dict with all income statement, balance sheet, cash flow, and
    notes fields ready for insertion into `pds_audited_financials`.

    Raises ValueError if required sections or fields are missing, or if
    hard integrity checks fail.
    """
    with pdfplumber.open(pdf_path) as pdf:
        metadata = _extract_metadata(pdf)
        income = _extract_income_statement(pdf)
        balance = _extract_balance_sheet(pdf)
        cashflow = _extract_cashflow(pdf)
        notes = _extract_notes(pdf)
        gc.collect()

    result: Dict[str, Any] = {
        **metadata,
        **income,
        **balance,
        **cashflow,
        **notes,
        "extraction_method": "pdfplumber_coordinate",
    }

    _validate(result)
    result["extraction_confidence"] = _calculate_confidence(result)
    result["sha256_hash"] = _sha256(result)

    logger.info(
        "[AUDITED] Extracted %s FY%s — confidence=%.1f%%",
        result.get("company_name"),
        result.get("financial_year"),
        float(result["extraction_confidence"]),
    )
    return result



# ─────────────────────────────────────────────────────────────────────────────
# OCR FALLBACK — for scanned (image-only) PDFs
# ─────────────────────────────────────────────────────────────────────────────

def _ocr_pdf_to_text(pdf_path: str) -> str:
    """
    Convert all pages of a scanned PDF to images and run Tesseract OCR.
    Returns the concatenated text from all pages.
    """
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(pdf_path, dpi=300)
    pages: List[str] = []
    for i, img in enumerate(images):
        logger.info("[OCR] Processing page %d/%d", i + 1, len(images))
        try:
            text = pytesseract.image_to_string(img, lang="eng")
            pages.append(text)
        except Exception as exc:
            logger.warning("[OCR] Page %d failed: %s", i + 1, exc)
    return "\n".join(pages)


def _ocr_find_amount(text: str, *patterns: str) -> Optional[int]:
    """
    Search `text` for the first pattern that matches a currency amount on the
    same line.  Returns the amount in cents, or None.

    Patterns are tried in order; the first match wins.
    Amount formats supported: 1,234,567  /  (1,234,567)  /  1234567
    """
    _AMT = r"[\-\(]?[\d,]+(?:\.\d+)?\)?"
    for pat in patterns:
        m = re.search(
            rf"(?i){pat}[^\n]{{0,60}}?({_AMT})",
            text,
        )
        if m:
            return _parse_amount(m.group(1))
    return None


def _ocr_find_year(text: str) -> Optional[int]:
    """Extract a 4-digit financial year (2000-2099) from OCR text."""
    for m in re.finditer(r"\b(20\d{2})\b", text):
        y = int(m.group(1))
        if 2000 <= y <= 2099:
            return y
    return None


def _ocr_find_company(text: str) -> str:
    """
    Best-effort company name from the first non-blank line of OCR text that
    looks like a proper name (initial caps, no pure-number content).
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 4:
            continue
        # Skip lines that are mostly numbers / keywords
        if re.match(r"^[\d,\.\(\)\-\s]+$", line):
            continue
        upper_words = sum(1 for w in line.split() if w and w[0].isupper())
        if upper_words >= 2:
            return line[:120]
    return ""


def extract_audited_financials_from_ocr(pdf_path: str) -> Dict[str, Any]:
    """
    Fallback extractor for scanned (image-only) PDFs.

    Runs Tesseract OCR on every page and applies regex patterns to locate
    key financial figures.  Returns the same dict shape as
    ``extract_audited_financials`` but with lower confidence and
    ``extraction_method='tesseract_ocr'``.

    This path intentionally never raises — on total failure it returns an
    empty skeleton so the API layer can present the manual confirmation form.
    """
    try:
        text = _ocr_pdf_to_text(pdf_path)
    except Exception as exc:
        logger.error("[OCR] PDF→image conversion failed: %s", exc)
        return {
            "extraction_method": "tesseract_ocr",
            "extraction_confidence": Decimal("0"),
            "sha256_hash": _sha256({}),
        }

    company_name = _ocr_find_company(text)
    financial_year = _ocr_find_year(text)

    # Infer year boundaries
    financial_year_end = f"{financial_year}-12-31" if financial_year else None
    financial_year_start = f"{financial_year - 1}-01-01" if financial_year else None

    result: Dict[str, Any] = {
        "company_name": company_name or None,
        "financial_year": financial_year,
        "financial_year_start": financial_year_start,
        "financial_year_end": financial_year_end,
        "currency": detect_currency(text),
        # Income Statement
        "turnover_cents": _ocr_find_amount(
            text,
            r"turnover",
            r"revenue",
            r"total\s+income",
            r"gross\s+income",
        ),
        "cost_of_sales_cents": _ocr_find_amount(
            text,
            r"cost\s+of\s+sales",
            r"cost\s+of\s+goods",
            r"direct\s+costs",
        ),
        "gross_profit_cents": _ocr_find_amount(
            text,
            r"gross\s+profit",
        ),
        "profit_before_tax_cents": _ocr_find_amount(
            text,
            r"profit\s+before\s+tax",
            r"net\s+profit\s+before\s+tax",
            r"income\s+before\s+tax",
        ),
        "tax_expense_cents": _ocr_find_amount(
            text,
            r"income\s+tax\s+expense",
            r"tax\s+expense",
            r"taxation",
        ),
        "profit_after_tax_cents": _ocr_find_amount(
            text,
            r"profit\s+after\s+tax",
            r"net\s+profit\s+after\s+tax",
            r"profit\s+for\s+the\s+year",
        ),
        # Balance Sheet
        "total_assets_cents": _ocr_find_amount(
            text,
            r"total\s+assets",
        ),
        "total_liabilities_cents": _ocr_find_amount(
            text,
            r"total\s+liabilities",
        ),
        "equity_cents": _ocr_find_amount(
            text,
            r"total\s+equity",
            r"shareholders['\s]+equity",
            r"net\s+assets",
        ),
        "cash_and_equivalents_cents": _ocr_find_amount(
            text,
            r"cash\s+and\s+cash\s+equivalents",
            r"cash\s+at\s+bank",
            r"cash\s+and\s+bank\s+balances",
        ),
        "trade_receivables_cents": _ocr_find_amount(
            text,
            r"trade\s+(?:and\s+other\s+)?receivables",
            r"accounts\s+receivable",
        ),
        "inventory_cents": _ocr_find_amount(
            text,
            r"inventories",
            r"stock",
        ),
        # Cash Flow
        "operating_cashflow_cents": _ocr_find_amount(
            text,
            r"(?:net\s+cash\s+(?:from|generated\s+(?:from|by))\s+operating)",
            r"operating\s+activities",
        ),
        "investing_cashflow_cents": _ocr_find_amount(
            text,
            r"(?:net\s+cash\s+(?:used\s+in|from)\s+investing)",
            r"investing\s+activities",
        ),
        "financing_cashflow_cents": _ocr_find_amount(
            text,
            r"(?:net\s+cash\s+(?:from|used\s+in)\s+financing)",
            r"financing\s+activities",
        ),
        "cash_at_end_cents": _ocr_find_amount(
            text,
            r"cash\s+at\s+(?:end|close)",
            r"closing\s+cash\s+balance",
        ),
        "cash_at_start_cents": _ocr_find_amount(
            text,
            r"cash\s+at\s+(?:beginning|start|opening)",
            r"opening\s+cash\s+balance",
        ),
        "extraction_method": "tesseract_ocr",
    }

    try:
        result["extraction_confidence"] = _calculate_confidence(result)
    except TypeError as exc:
        # _calculate_confidence assumes that if a field key is present, its
        # value is a real number — true for the coordinate path (required
        # fields are validated before this is ever called), not true here:
        # OCR always sets every key, with None on a failed regex match. A
        # missing match (e.g. "profit before tax" / "tax expense" not found
        # in the OCR text) reaches an arithmetic check on None and raises.
        # Fail the same way total OCR failure already does above, rather
        # than letting this surface as an unhandled crash.
        logger.error(
            "[OCR] Confidence calculation failed — required fields not found "
            "in OCR text (%s)", exc,
        )
        return {
            "extraction_method": "tesseract_ocr",
            "extraction_confidence": Decimal("0"),
            "sha256_hash": _sha256({}),
        }
    result["sha256_hash"] = _sha256(result)

    logger.info(
        "[OCR] Extracted %s FY%s — confidence=%.1f%%",
        result.get("company_name"),
        result.get("financial_year"),
        float(result["extraction_confidence"]),
    )
    return result


__all__ = ["extract_audited_financials", "extract_audited_financials_from_ocr"]
