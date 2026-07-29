import re
import statistics
from typing import Dict, List, Optional, Tuple

from ..config import (
    CLASSIFIER_ABSOLUTE_CEILING_CENTS,
    CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD,
    CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_DEN,
    CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_NUM,
)

# ── ONTOLOGY v2.0 ─────────────────────────────────────────────────────────────
# Every keyword group maps to a specific role.
# Order of evaluation is fixed and deterministic.
# Every path returns a (role, classification_reason) tuple.
# ─────────────────────────────────────────────────────────────────────────────

# Strip categories — excluded from all financial calculations
_OPENING_BALANCE_KEYWORDS = frozenset({
    "b/fwd", "balance b/fwd", "balance b/f", "opening balance",
    "balance brought forward", "brought forward"
})
_CLOSING_BALANCE_KEYWORDS = frozenset({
    "balance at period end", "closing balance", "balance carried forward",
    "balance c/fwd", "balance c/f"
})

# Loan inflows — positive: loan_inflow, negative: loan_repayment
_LOAN_KEYWORDS = frozenset({
    "loan", "facility", "disbursement", "loan repayment",
    "fuliza", "tala", "branch loan", "zenka", "timia", "okolea",
    "kcb loop", "equity loan", "ncba loop",
    # Digital lenders / mobile credit products
    "stawi", "zidisha", "mshwari", "kcb m-pesa",
    # Equity Bank credit products
    "jiinue", "jiendeleze",
    # OD facility term — "facility" already catches "od facility"; this covers bare "od limit"
    "od limit",
})

# Known microfinance and bank paybill patterns for loan repayment detection
_LOAN_REPAYMENT_PATTERNS = frozenset({
    "choice microfinance", "faulu", "kwft", "smep", "sumac",
    "rafiki microfinance", "century microfinance", "uwezo",
    "oda collection",
    # Overdraft-specific repayment terms (no "loan" substring to catch via _LOAN_KEYWORDS)
    "overdraft repayment", "od repayment", "od recovery",
    # Digital lenders identified via statement scan — no "loan" substring in descriptors
    "tendepay",
})

# Capital injection (positive only)
# Note: "capital" as a standalone word matches company names (e.g. "Fourth Generation Capital Ltd")
# Only match multi-word phrases that unambiguously indicate an equity injection
_CAPITAL_KEYWORDS = frozenset({
    "equity injection", "shareholder contribution", "director contribution",
    "owner contribution", "capital injection", "share capital"
})

# Company name suffixes that contain capital/investment keywords but are NOT injections
_COMPANY_SUFFIXES = frozenset({
    "capital limited", "capital ltd", "capital llp", "capital plc",
    "investment limited", "investment ltd", "investment trust",
    "investments limited", "investments ltd",
    "trust registered", "africa trust",
})

# Reversal and refund credits — auto-excluded from revenue
_REVERSAL_KEYWORDS = frozenset({
    "reversal", "refund", "chargeback", "reversed", "reverse",
    "refer to drawer", "insufficient funds", "dishonoured", "dishonored",
    "unpaid cheque", "unpaid check", "returned cheque", "returned check",
    "bounced", "chq rejected", "cheque rejected", "failed payment",
    "payment failed", "rev ", "rev/", "rev-"
})

# Non-operational revenue — grants, rental, government transfers
_NON_OP_REVENUE_KEYWORDS = frozenset({
    "grant", "rental income", "rent income", "subsidy",
    "government transfer", "ngcdf", "constituency", "bursary"
})

# Revenue operational — confirmed trading income
_REVENUE_OP_KEYWORDS = frozenset({
    "sale", "pos", "mpesa", "payment received", "client payment",
    "receipt", "c2b", "till", "paybill receipt"
})

# Payroll — outflows only
_PAYROLL_KEYWORDS = frozenset({
    "salary", "payroll", "wages", "staff payment", "net pay",
    "salaries", "wage payment"
})

# Tax payments — outflows only
_TAX_KEYWORDS = frozenset({
    "tax", "kra", "vat", "paye", "withholding tax", "income tax",
    "corporate tax", "turnover tax"
})

# Bank charges and fees — outflows only
_BANK_CHARGE_KEYWORDS = frozenset({
    "charge", "fee", "commission", "excise", "excise duty",
    "transaction fee", "transfer fee", "withdrawal charge",
    "maintenance fee", "ledger fee", "monthly fee", "annual fee",
    "pesalink fee", "funds transfer debit fee", "debit fee",
    "alert crg", "crg excise", "kplcprepaidcomm", "int.coll",
    "interest run", "interest charge", "interest collected",
    "agency charge", "atm charge", "unpaid cheque commission"
})

# Cash withdrawals — outflows only
_CASH_WITHDRAWAL_KEYWORDS = frozenset({
    "atm cash", "cash withdrawal", "agent wdl", "cheque withdrawal",
    "agent withdrawal", "atm withdrawal", "cash draw"
})

# Airtime and data — outflows only
_AIRTIME_KEYWORDS = frozenset({
    "airtime", "recharge", "data bundle", "bundle purchase",
    "safaricom data", "airtime purchase"
})

# Bill payments — outflows only
_BILL_PAYMENT_KEYWORDS = frozenset({
    "//bill//", "pay bill", "paybill", "bill payment",
    "utility payment", "kplc", "nairobi water", "kenya power",
    "pay utility", "mpesab2c"
})

# Merchant and POS purchases — outflows only
_MERCHANT_KEYWORDS = frozenset({
    "merchant payment", "pos txn", "pos purchase",
    "supermarket", "naivas", "quickmart", "carrefour",
    "java", "chicken inn", "cinemax"
})

# Mobile money transfers — outflows only
_MOBILE_TRANSFER_KEYWORDS = frozenset({
    "mobile money tr", "mobile payment", "send money",
    "customer transfer", "transfer of funds"
})

# PesaLink inflows — credits only
_PESALINK_INFLOW_KEYWORDS = frozenset({
    "pesalink", "pesa link"
})

# Named counterparty threshold — positive amounts above this get needs_review.
# Flat fallback used when a per-deal relative threshold can't be computed (see
# compute_relative_large_positive_threshold_cents below, PAR-89).
_LARGE_POSITIVE_THRESHOLD_CENTS = 10_000_000  # KES 100,000

# PAR-89 part A: sample-size cutoff, modified-z-score multiplier, and absolute
# ceiling now live in config.py (validated at import time) instead of as
# module constants here, so they can be tuned from real review-queue data
# without a code change. Values are unchanged from the original PAR-89 fix.
_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD = CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD
_MODIFIED_Z_SCORE_MULTIPLIER_NUM = CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_NUM
_MODIFIED_Z_SCORE_MULTIPLIER_DEN = CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_DEN
_ABSOLUTE_CEILING_CENTS = CLASSIFIER_ABSOLUTE_CEILING_CENTS

# Foreign currency codes for conversion detection
_FX_CURRENCY_CODES = frozenset({"EUR", "USD", "GBP", "CHF", "JPY", "CNY", "AED", "ZAR"})
_FX_CONVERSION_KEYWORDS = frozenset({"CONVERSION TRANSFER", "FX CONVERSION", "CURRENCY CONVERSION", "CONVERSION"})
_FX_RATE_PATTERN = re.compile(r'AT\s+\d+\.?\d*')


def _classify_currency_conversion(desc_upper: str) -> bool:
    """Return True if the description matches a foreign currency conversion."""
    # Pattern 1: explicit conversion keyword + foreign currency code
    has_conversion = any(kw in desc_upper for kw in _FX_CONVERSION_KEYWORDS)
    has_currency = any(cc in desc_upper for cc in _FX_CURRENCY_CODES)
    if has_conversion and has_currency:
        return True

    # Pattern 2: "EUR/USD/etc <amount> AT <rate> TRF FROM/TRANSFER FROM"
    if has_currency:
        if _FX_RATE_PATTERN.search(desc_upper) and (
            "TRF FROM" in desc_upper or "TRANSFER FROM" in desc_upper
        ):
            return True

    # Pattern 3: "TO KSH/TO KES" + foreign currency code
    if has_currency and ("TO KSH" in desc_upper or "TO KES" in desc_upper):
        return True

    return False

def _format_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


def compute_relative_large_positive_threshold_cents(
    all_txns: List[Dict],
) -> Tuple[int, Optional[int], Optional[int]]:
    """
    PAR-89: a per-deal "this credit is unusually large FOR THIS BUSINESS"
    threshold, replacing a flat KES 100,000 cutoff that flagged every large
    transaction for a high-revenue business (whose routine transactions are
    all large) while letting a same-sized outlier slip through untouched for
    a small, low-volume one.

    This is a heuristic upgrade, not a precision-tuned model (see PAR-89) —
    a defensible starting point, not a solved formula:
      - Method: modified z-score via median + scaled MAD (Iglewicz & Hoaglin,
        1993), a standard robust-outlier technique — robust because the
        median/MAD aren't themselves dragged around by the outliers being
        measured, unlike a mean+stdev approach.
      - threshold = median + (mad * _MODIFIED_Z_SCORE_MULTIPLIER_NUM)
        // _MODIFIED_Z_SCORE_MULTIPLIER_DEN ≈ median + 5.19 * MAD.
      - The absolute ceiling (_ABSOLUTE_CEILING_CENTS) is applied separately
        by the caller (classify_with_reason) — this function only computes
        the relative number.

    Falls back to the flat _LARGE_POSITIVE_THRESHOLD_CENTS (signalled by
    returning median=None) when:
      - the deal has fewer than _MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD
        transactions — a median/MAD computed on a handful of rows is noise,
        not signal; or
      - MAD is 0 (e.g. most transactions are near-identical in size) — the
        modified z-score is degenerate in that case, not merely small.

    Returns (threshold_cents, median_abs_cents_or_None, mad_abs_cents_or_None).
    median and mad are None together whenever the flat fallback was used, so
    callers know not to build a "Nx median" reason string (or a PAR-89 part B
    review_threshold_log diagnostics row) from them.
    """
    amounts = [abs(int(t.get("signed_amount_cents", 0))) for t in all_txns if t.get("signed_amount_cents")]
    if len(amounts) < _MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD:
        return _LARGE_POSITIVE_THRESHOLD_CENTS, None, None
    median = int(statistics.median(amounts))
    mad = int(statistics.median([abs(a - median) for a in amounts]))
    if mad == 0:
        return _LARGE_POSITIVE_THRESHOLD_CENTS, None, None
    threshold = median + (mad * _MODIFIED_Z_SCORE_MULTIPLIER_NUM) // _MODIFIED_Z_SCORE_MULTIPLIER_DEN
    return threshold, median, mad


DEBIT_ONLY_ROLES = {
    "bank_charge", "loan_repayment", "tax_payment", "supplier_payment",
    "merchant_payment", "reversal_debit", "pesalink_outflow", "payroll"
}

CREDIT_ONLY_ROLES = {
    "revenue_operational", "loan_inflow", "capital_injection",
    "reversal_credit", "pesalink_inflow", "mpesa_inflow"
}


def _keyword_classify(descriptor: str, amount_cents: int) -> Optional[Tuple[str, str]]:
    """
    Deterministic keyword classification.
    Returns (role, classification_reason) tuple or None if no match.

    Evaluation order is fixed — first match wins:
    1. Strip categories (opening/closing balance)
    2. Loan inflow / loan repayment
    3. Capital injection
    4. Reversal credit
    5. Non-operational revenue
    6. Payroll
    7. Tax payment
    8. Bank charges
    9. Cash withdrawal
    10. Airtime
    11. Bill payment
    12. Merchant payment
    13. Mobile money transfer
    14. PesaLink inflow
    15. Revenue operational
    """
    d = (descriptor or "").lower()
    amt = amount_cents

    # Currency conversion — must run before revenue/supplier rules to avoid misclassification
    if _classify_currency_conversion(d.upper()):
        return ("currency_conversion", "keyword_match:currency_conversion")

    # PAYED / PAID prefix → revenue_operational (must run before all other checks)
    # Covers "PAYED BY ...", "PAID BY ...", and "PAYED 703193... BY:FLIXNET/..."
    if d.startswith("payed ") or d.startswith("paid by"):
        return ("revenue_operational", "keyword_match:payed_by_prefix")

    # MPS credit prefix → revenue_operational
    if d.startswith("mps") and amt > 0:
        return ("revenue_operational", "keyword_match:mps_credit_inflow")

    # 1. Strip categories
    for kw in _OPENING_BALANCE_KEYWORDS:
        if kw in d:
            return ("opening_balance", f"keyword_match:{kw}:opening_balance")
    for kw in _CLOSING_BALANCE_KEYWORDS:
        if kw in d:
            return ("closing_balance", f"keyword_match:{kw}:closing_balance")

    # Swift wire charges — always a bank fee; must precede loan keyword check to
    # prevent lender names in the descriptor (e.g. "jiinue") from firing first.
    if "swift charge" in d:
        return ("bank_charge", "keyword_match:swift_charge_fee")

    # 2. Loan keywords
    for kw in _LOAN_KEYWORDS:
        if kw in d:
            if amt > 0:
                return ("loan_inflow", f"keyword_match:{kw}:loan_keywords")
            else:
                return ("loan_repayment", f"keyword_match:{kw}:loan_keywords")
    for kw in _LOAN_REPAYMENT_PATTERNS:
        if kw in d:
            return ("loan_repayment", f"keyword_match:{kw}:loan_repayment_patterns")

    # 3. Capital injection (positive only)
    for kw in _CAPITAL_KEYWORDS:
        if kw in d:
            if amt > 0:
                return ("capital_injection", f"keyword_match:{kw}:capital_keywords")
            else:
                return ("supplier", f"keyword_match:{kw}:capital_keywords_negative")

    # 4. Reversal credit
    for kw in _REVERSAL_KEYWORDS:
        if kw in d:
            if amt > 0:
                return ("reversal_credit", f"keyword_match:{kw}:reversal_keywords")
            else:
                return ("reversal_debit", f"keyword_match:{kw}:reversal_keywords")

    # 5. Non-operational revenue
    for kw in _NON_OP_REVENUE_KEYWORDS:
        if kw in d:
            return ("revenue_non_operational", f"keyword_match:{kw}:non_op_revenue_keywords")

    # 6. Payroll (negative only — salary received is revenue_operational)
    for kw in _PAYROLL_KEYWORDS:
        if kw in d:
            if amt < 0:
                return ("payroll", f"keyword_match:{kw}:payroll_keywords")
            else:
                return ("revenue_operational", f"keyword_match:{kw}:payroll_keywords_inbound")

    # 7. Tax payment (debit-only — payments TO KRA; credits handled by reversal/direction guard)
    for kw in _TAX_KEYWORDS:
        if kw in d:
            if amt < 0:
                return ("tax_payment", f"keyword_match:{kw}:tax_keywords")
            break  # credit with tax keyword — fall through to direction guard

    # 8. Bank charges
    for kw in _BANK_CHARGE_KEYWORDS:
        if kw in d:
            return ("bank_charge", f"keyword_match:{kw}:bank_charge_keywords")

    # 9. Cash withdrawal
    for kw in _CASH_WITHDRAWAL_KEYWORDS:
        if kw in d:
            return ("cash_withdrawal", f"keyword_match:{kw}:cash_withdrawal_keywords")

    # 10. Airtime
    for kw in _AIRTIME_KEYWORDS:
        if kw in d:
            return ("airtime_purchase", f"keyword_match:{kw}:airtime_keywords")

    # 11. Bill payment
    for kw in _BILL_PAYMENT_KEYWORDS:
        if kw in d:
            if amt < 0:
                return ("bill_payment", f"keyword_match:{kw}:bill_payment_keywords")
            else:
                return ("revenue_operational", f"keyword_match:{kw}:bill_payment_inbound")

    # Bank to Mobile — Equity Bank B2C to phone number
    if "bank to mobile" in d:
        if amt < 0:
            return ("supplier", "keyword_match:bank_to_mobile_outflow")
        else:
            return ("supplier", "keyword_match:bank_to_mobile_outflow")

    # EazzyBiz B2C bulk MPESA outflow → supplier_payment (direction-guarded)
    if "eazzybiz" in d and amt < 0:
        return ("supplier_payment", "keyword_match:eazzybiz_b2c_outflow")

    # EAZZY-FUNDS TRNSF — Equity Bank fund transfer (distinct from EazzyBiz B2C)
    if "eazzy-funds" in d or "eazzy funds" in d:
        if amt > 0:
            return ("revenue_operational", "keyword_match:eazzy_funds_inflow")
        else:
            return ("supplier", "keyword_match:eazzy_funds_outflow")

    # USSD MPESA individual send → supplier_payment (direction-guarded)
    if d.startswith("ussd/mpesa") and amt < 0:
        return ("supplier_payment", "keyword_match:ussd_mpesa_outflow")

    # USSD bulk credit from named company → revenue_operational
    if d.startswith("ussd/") and amt > 0:
        return ("revenue_operational", "keyword_match:ussd_credit_inflow")

    # OD sweep credit → loan_inflow (direction-guarded)
    if "sweep trf" in d and amt > 0:
        return ("loan_inflow", "keyword_match:od_sweep_credit")

    # Cheque receipt (credit) → revenue_operational (must come before supermarket debit rule)
    if "chq:" in d and amt > 0:
        return ("revenue_operational", "keyword_match:cheque_receipt_credit")

    # Supermarket cheque → supplier_payment (before generic cheque-to-merchant path)
    if "chq:" in d and "supermarket" in d:
        return ("supplier_payment", "keyword_match:supermarket_cheque")

    # 12. Merchant payment
    for kw in _MERCHANT_KEYWORDS:
        if kw in d:
            return ("merchant_payment", f"keyword_match:{kw}:merchant_keywords")

    # 13. Mobile money transfer
    for kw in _MOBILE_TRANSFER_KEYWORDS:
        if kw in d:
            if amt < 0:
                return ("mobile_money_transfer", f"keyword_match:{kw}:mobile_transfer_keywords")
            else:
                return ("mpesa_inflow", f"keyword_match:{kw}:mobile_transfer_keywords_inbound")

    # 14. PesaLink — channel only; direction determines role, no amount threshold
    for kw in _PESALINK_INFLOW_KEYWORDS:
        if kw in d:
            if amt > 0:
                return ("pesalink_inflow", f"keyword_match:{kw}:pesalink_keywords")
            else:
                return ("pesalink_outflow", f"keyword_match:{kw}:pesalink_keywords_outbound")

    # 15. Revenue operational
    for kw in _REVENUE_OP_KEYWORDS:
        if kw in d:
            return ("revenue_operational", f"keyword_match:{kw}:revenue_op_keywords")

    return None


def classify(
    txn: Dict,
    *,
    large_positive_threshold_cents: Optional[int] = None,
    median_txn_abs_cents: Optional[int] = None,
) -> str:
    """
    Deterministic, rule-based classification. Returns role string only.
    Use classify_with_reason() to get the full (role, reason) tuple.
    """
    role, _ = classify_with_reason(
        txn,
        large_positive_threshold_cents=large_positive_threshold_cents,
        median_txn_abs_cents=median_txn_abs_cents,
    )
    return role


def classify_with_reason(
    txn: Dict,
    *,
    large_positive_threshold_cents: Optional[int] = None,
    median_txn_abs_cents: Optional[int] = None,
    mad_txn_abs_cents: Optional[int] = None,
    flag_diagnostics_out: Optional[Dict] = None,
) -> Tuple[str, str]:
    """
    Deterministic, rule-based classification with audit trail.
    Returns (role, classification_reason) tuple.

    Order:
    1. Transfer flag
    2. Keyword match on normalized_descriptor
    3. Large positive fallback -> needs_review
    4. Sign-based fallback

    large_positive_threshold_cents / median_txn_abs_cents (PAR-89): the
    per-deal relative statistic from compute_relative_large_positive_threshold_cents(),
    computed once per deal by the caller (see pipeline.py) and passed through
    for every transaction in that deal. Both default to None — matching
    pre-PAR-89 behavior (the flat KES 100,000 threshold, no median context) —
    for callers that classify a single transaction with no deal context, e.g.
    unit tests.

    mad_txn_abs_cents (PAR-89 part B): same per-deal computation as
    median_txn_abs_cents, threaded through only to populate
    flag_diagnostics_out — it plays no role in the classification decision
    itself.

    flag_diagnostics_out (PAR-89 part B, optional): if provided, this dict is
    populated in place with the raw numbers behind a large-positive
    needs_review flag (median_cents, mad_cents, threshold_cents, amount_cents,
    ratio) whenever that specific branch fires, for the caller to persist as
    a review_threshold_log row. Left untouched (empty) for every other
    classification outcome. Default None means "don't bother" — existing
    callers see no behavior change.
    """
    if txn.get("is_transfer"):
        return ("transfer", "is_transfer:flag")

    descriptor = txn.get("normalized_descriptor", "")
    amt = int(txn.get("signed_amount_cents", 0))

    result = _keyword_classify(descriptor, amt)
    if result is not None:
        role, reason = result
    elif amt > 0:
        threshold = (
            large_positive_threshold_cents
            if large_positive_threshold_cents is not None
            else _LARGE_POSITIVE_THRESHOLD_CENTS
        )
        # Absolute ceiling (PAR-89 #3) — kept separate from the relative
        # logic: no business's own transaction pattern can push the
        # effective needs_review trigger above this hard cap.
        effective_threshold = min(threshold, _ABSOLUTE_CEILING_CENTS)
        if amt >= effective_threshold:
            if effective_threshold == _ABSOLUTE_CEILING_CENTS and effective_threshold < threshold:
                detail = f"exceeds the {_format_kes(_ABSOLUTE_CEILING_CENTS)} hard cap"
            elif median_txn_abs_cents:
                ratio = amt / median_txn_abs_cents
                detail = f"{ratio:.1f}x this business's median transaction size"
            else:
                detail = (
                    f"exceeds flat {_format_kes(_LARGE_POSITIVE_THRESHOLD_CENTS)} threshold "
                    "(insufficient transaction history for a per-deal statistic)"
                )
            role, reason = (
                "needs_review",
                f"fallback:large_positive_no_keyword_match:{_format_kes(amt)} credit, no keyword match, {detail}",
            )
            if flag_diagnostics_out is not None:
                flag_diagnostics_out.update(
                    {
                        "median_cents": median_txn_abs_cents,
                        "mad_cents": mad_txn_abs_cents,
                        "threshold_cents": effective_threshold,
                        "amount_cents": amt,
                        "ratio": (amt / median_txn_abs_cents) if median_txn_abs_cents else None,
                    }
                )
        else:
            role, reason = "revenue_operational", "fallback:positive_amount"
    elif amt < 0:
        role, reason = "supplier", "fallback:negative_amount"
    else:
        role, reason = "other", "fallback:zero_amount"

    # Direction consistency guard
    if role in DEBIT_ONLY_ROLES and amt > 0:
        return ("needs_review", f"direction_conflict:{role}_on_credit")
    if role in CREDIT_ONLY_ROLES and amt < 0:
        return ("needs_review", f"direction_conflict:{role}_on_debit")

    return (role, reason)
