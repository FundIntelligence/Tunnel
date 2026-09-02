"""
Tests for Parity ontology v2.0 classifier.
Every test verifies both role and classification_reason format.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.classifier import classify, classify_with_reason


def txn(descriptor, amount):
    return {"normalized_descriptor": descriptor, "signed_amount_cents": amount}


# ── STRIP CATEGORIES ──────────────────────────────────────────────────────────

def test_opening_balance_stripped():
    role, reason = classify_with_reason(txn("balance b/fwd", 0))
    assert role == "opening_balance"
    assert "opening_balance" in reason

def test_closing_balance_stripped():
    role, reason = classify_with_reason(txn("balance at period end", 100000))
    assert role == "closing_balance"
    assert "closing_balance" in reason

# ── LOAN INFLOW ───────────────────────────────────────────────────────────────

def test_loan_inflow_keyword_disbursement():
    role, reason = classify_with_reason(txn("fourth generation capital loan disbursement", 29849325))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_loan_inflow_keyword_facility():
    role, reason = classify_with_reason(txn("credit facility drawdown", 50000000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_loan_repayment_negative():
    role, reason = classify_with_reason(txn("loan repayment kcb", -1250000))
    assert role == "loan_repayment"
    assert "keyword_match" in reason

def test_loan_repayment_microfinance_pattern():
    role, reason = classify_with_reason(txn("pay bill online to 444174 choice microfinance bank", -320000))
    assert role == "loan_repayment"
    assert "keyword_match" in reason

def test_fuliza_repayment():
    role, reason = classify_with_reason(txn("fuliza repayment safaricom", -234000))
    assert role == "loan_repayment"
    assert "keyword_match" in reason

# ── CAPITAL INJECTION ─────────────────────────────────────────────────────────

def test_capital_injection_equity():
    role, reason = classify_with_reason(txn("equity injection from shareholder", 50000000))
    assert role == "capital_injection"
    assert "keyword_match" in reason

def test_capital_injection_director():
    role, reason = classify_with_reason(txn("director contribution to business", 10000000))
    assert role == "capital_injection"
    assert "keyword_match" in reason

# ── REVERSAL ──────────────────────────────────────────────────────────────────

def test_reversal_credit():
    role, reason = classify_with_reason(txn("reversed aba6ce209025 safeways express", 4000000))
    assert role == "reversal_credit"
    assert "keyword_match" in reason

def test_reversal_debit():
    role, reason = classify_with_reason(txn("reversal of failed payment", -1900000))
    assert role == "reversal_debit"
    assert "keyword_match" in reason

# ── PAYROLL ───────────────────────────────────────────────────────────────────

def test_payroll_outflow():
    role, reason = classify_with_reason(txn("salary payment staff net pay", -10000000))
    assert role == "payroll"
    assert "keyword_match" in reason

def test_salary_inbound_is_revenue():
    role, reason = classify_with_reason(txn("salary credit from employer", 8400000))
    assert role == "revenue_operational"
    assert "keyword_match" in reason

# ── TAX PAYMENT ───────────────────────────────────────────────────────────────

def test_tax_payment_kra():
    role, reason = classify_with_reason(txn("kra paye payment march 2025", -500000))
    assert role == "tax_payment"
    assert "keyword_match" in reason

def test_tax_payment_vat():
    role, reason = classify_with_reason(txn("vat remittance quarterly", -320000))
    assert role == "tax_payment"
    assert "keyword_match" in reason

# ── BANK CHARGES ──────────────────────────────────────────────────────────────

def test_bank_charge_excise():
    role, reason = classify_with_reason(txn("excise duty for the fee", -500))
    assert role == "bank_charge"
    assert "keyword_match" in reason

def test_bank_charge_maintenance():
    role, reason = classify_with_reason(txn("msme bronze maintenance fee monthly", -10000))
    assert role == "bank_charge"
    assert "keyword_match" in reason

def test_bank_charge_interest():
    role, reason = classify_with_reason(txn("int.coll 01-01-2025 to 31-01-2025", -1000))
    assert role == "bank_charge"
    assert "keyword_match" in reason

def test_bank_charge_alert():
    role, reason = classify_with_reason(txn("debit alert crg cb0567683", -3500))
    assert role == "bank_charge"
    assert "keyword_match" in reason

# ── CASH WITHDRAWAL ───────────────────────────────────────────────────────────

def test_cash_withdrawal_atm():
    role, reason = classify_with_reason(txn("atm cash kcb 4243142016004052", -2000000))
    assert role == "cash_withdrawal"
    assert "keyword_match" in reason

def test_cash_withdrawal_agent():
    role, reason = classify_with_reason(txn("agent wdl sz09bfcceqn0", -1500000))
    assert role == "cash_withdrawal"
    assert "keyword_match" in reason

# ── AIRTIME ───────────────────────────────────────────────────────────────────

def test_airtime_purchase():
    role, reason = classify_with_reason(txn("airtime purchase safaricom", -5000))
    assert role == "airtime_purchase"
    assert "keyword_match" in reason

def test_data_bundle():
    role, reason = classify_with_reason(txn("customer bundle purchase safaricom data", -20000))
    assert role == "airtime_purchase"
    assert "keyword_match" in reason

# ── BILL PAYMENT ──────────────────────────────────────────────────────────────

def test_bill_payment_mpesa():
    role, reason = classify_with_reason(txn("mpesab2c-11 0710642294 bill mb bp", -5000000))
    assert role == "bill_payment"
    assert "keyword_match" in reason

def test_bill_payment_kplc():
    role, reason = classify_with_reason(txn("kplc prepaid 14243228146 properties kiambaa", -20000))
    assert role == "bill_payment"
    assert "keyword_match" in reason

def test_bill_payment_paybill():
    role, reason = classify_with_reason(txn("pay bill online to 7847061 uber bv", -150000))
    assert role == "bill_payment"
    assert "keyword_match" in reason

# ── MERCHANT PAYMENT ─────────────────────────────────────────────────────────

def test_merchant_payment_pos():
    role, reason = classify_with_reason(txn("pos txn 4243142016004052 naivas supermarket", -109360))
    assert role == "merchant_payment"
    assert "keyword_match" in reason

def test_merchant_payment_named():
    role, reason = classify_with_reason(txn("merchant payment to 7099197 naivas", -50000))
    assert role == "merchant_payment"
    assert "keyword_match" in reason

# ── MOBILE MONEY ──────────────────────────────────────────────────────────────

def test_mobile_money_transfer_outbound():
    role, reason = classify_with_reason(txn("mobile money tr mm230559o0589 custom", -17439700))
    assert role == "mobile_money_transfer"
    assert "keyword_match" in reason

def test_mobile_money_inbound():
    role, reason = classify_with_reason(txn("mobile payment received customer", 4300500))
    assert role == "mpesa_inflow"
    assert "keyword_match" in reason

# ── PESALINK ──────────────────────────────────────────────────────────────────

def test_pesalink_inflow():
    role, reason = classify_with_reason(txn("pesalink inbound transfer from bank", 9995000))
    assert role == "pesalink_inflow"
    assert "keyword_match" in reason

def test_pesalink_outbound_large():
    """PesaLink outbound routes to pesalink_outflow regardless of amount."""
    role, reason = classify_with_reason(txn("pesalink 16958003230901 payment", -40000000))
    assert role == "pesalink_outflow"
    assert "keyword_match" in reason

def test_pesalink_outbound_small():
    """PesaLink outbound routes to pesalink_outflow regardless of amount."""
    role, reason = classify_with_reason(txn("pesalink transfer outbound small amount", -500000))
    assert role == "pesalink_outflow"
    assert "keyword_match" in reason

# ── REVENUE OPERATIONAL ───────────────────────────────────────────────────────

def test_revenue_mpesa_c2b():
    role, reason = classify_with_reason(txn("mpesa c2b customer payment receipt", 100000))
    assert role == "revenue_operational"
    assert "keyword_match" in reason

def test_revenue_pos_receipt():
    role, reason = classify_with_reason(txn("pos receipt sale confirmed", 500000))
    assert role == "revenue_operational"
    assert "keyword_match" in reason

# ── FALLBACK ──────────────────────────────────────────────────────────────────

def test_large_positive_fallback_needs_review():
    role, reason = classify_with_reason(txn("the somo africa trust payment", 53760000))
    assert role == "needs_review"
    assert "fallback" in reason
    assert "large_positive" in reason

def test_small_positive_fallback_revenue():
    role, reason = classify_with_reason(txn("unknown small credit", 50000))
    assert role == "revenue_operational"
    assert "fallback" in reason

def test_negative_fallback_supplier():
    role, reason = classify_with_reason(txn("unknown debit", -100000))
    assert role == "supplier"
    assert "fallback" in reason

def test_zero_fallback_other():
    role, reason = classify_with_reason(txn("zero amount row", 0))
    assert role == "other"
    assert "fallback" in reason

# ── TRANSFER FLAG ─────────────────────────────────────────────────────────────

def test_transfer_flag_overrides_all():
    role, reason = classify_with_reason({"is_transfer": True, "normalized_descriptor": "loan disbursement", "signed_amount_cents": 50000000})
    assert role == "transfer"
    assert "is_transfer" in reason

# ── CLASSIFICATION REASON ALWAYS POPULATED ────────────────────────────────────

def test_classification_reason_never_empty():
    test_txns = [
        txn("balance b/fwd", 0),
        txn("loan disbursement", 5000000),
        txn("salary payment", -1000000),
        txn("unknown", 999),
        txn("unknown large", 50000000),
        txn("unknown debit", -999),
    ]
    for t in test_txns:
        _, reason = classify_with_reason(t)
        assert reason and len(reason) > 0, f"Empty reason for: {t}"

# ── BACKWARD COMPATIBILITY ────────────────────────────────────────────────────

def test_classify_returns_string():
    role = classify(txn("mpesa payment", 100000))
    assert isinstance(role, str)
    assert len(role) > 0


# ── SESSION 7: CLASSIFIER GAP FIXES ──────────────────────────────────────────

def test_eazzybiz_debit_supplier_payment():
    role, reason = classify_with_reason(txn("07722000000 eazzybiz trsf mpesa", -500000))
    assert role == "supplier_payment"
    assert "eazzybiz_b2c_outflow" in reason

def test_eazzybiz_credit_not_caught():
    # EazzyBiz credit must NOT be classified as supplier_payment
    role, _ = classify_with_reason(txn("eazzybiz trsf mpesa", 500000))
    assert role != "supplier_payment"

def test_ussd_mpesa_debit_supplier_payment():
    role, reason = classify_with_reason(txn("ussd/mpesa/2547 0722123456/ref james kariuki abc", -150000))
    assert role == "supplier_payment"
    assert "ussd_mpesa_outflow" in reason

def test_ussd_mpesa_credit_not_caught():
    # USSD MPESA credit must NOT hit the debit rule
    role, _ = classify_with_reason(txn("ussd/mpesa/2547 0722123456/ref james kariuki abc", 150000))
    assert role != "supplier_payment"

def test_od_sweep_credit_loan_inflow():
    role, reason = classify_with_reason(txn("sweep trf from: 118od00002479", 533294))
    assert role == "loan_inflow"
    assert "od_sweep_credit" in reason

def test_od_sweep_debit_not_caught():
    # Sweep debit must NOT be classified as loan_inflow
    role, _ = classify_with_reason(txn("sweep trf from: 118od00002479", -533294))
    assert role != "loan_inflow"

def test_cheque_credit_revenue_operational():
    role, reason = classify_with_reason(txn("chq:094038 magunas super stores", 194838))
    assert role == "revenue_operational"
    assert "cheque_receipt_credit" in reason

def test_cheque_supermarket_debit_supplier_payment():
    # Existing supermarket debit rule must still fire
    role, reason = classify_with_reason(txn("chq:000731 silmatt supermarket s8627174", -45000))
    assert role == "supplier_payment"
    assert "supermarket_cheque" in reason

def test_ussd_bulk_credit_revenue_operational():
    role, reason = classify_with_reason(txn("ussd/chajay & sons limited/", 260000))
    assert role == "revenue_operational"
    assert "ussd_credit_inflow" in reason

def test_ussd_mpesa_debit_takes_priority_over_ussd_credit_rule():
    # ussd/mpesa debit must exit at Step 2, not fall through to USSD credit rule
    role, reason = classify_with_reason(txn("ussd/mpesa/2547 0722123456/ref name abc", -150000))
    assert role == "supplier_payment"
    assert "ussd_mpesa_outflow" in reason


# ── CURRENCY CONVERSION ───────────────────────────────────────────────────────

def test_eur_conversion_transfer_credit():
    role, reason = classify_with_reason(txn("conversion transfer of eur 40,000 to ksh 03-03-25", 536000000))
    assert role == "currency_conversion"
    assert "keyword_match" in reason

def test_eur_with_rate_trf_from():
    role, reason = classify_with_reason(txn("eur 18950 at 145.90 trf from eur a/c 06-05-25", 276633670))
    assert role == "currency_conversion"
    assert "keyword_match" in reason

def test_usd_to_kes_conversion():
    role, reason = classify_with_reason(txn("usd to kes conversion - usd 10,000", 129000000))
    assert role == "currency_conversion"
    assert "keyword_match" in reason

def test_gbp_fx_conversion():
    role, reason = classify_with_reason(txn("fx conversion gbp 5000 to ksh", 85000000))
    assert role == "currency_conversion"
    assert "keyword_match" in reason

def test_eur_mention_no_conversion_keyword():
    """EUR mentioned without conversion keyword should NOT be currency_conversion."""
    role, _ = classify_with_reason(txn("payment to european supplier for goods", -50000000))
    assert role != "currency_conversion"

def test_conversion_debit_side():
    role, reason = classify_with_reason(txn("conversion transfer ksh to eur a/c", -500000000))
    assert role == "currency_conversion"
    assert "keyword_match" in reason


# ── KRA TAX PAYMENT ───────────────────────────────────────────────────────────

class TestKRATaxPayment:
    """KRA tax payment classification with directional flow validation."""

    def test_kra_tax_payment_debit(self):
        role, reason = classify_with_reason(txn("paid to kra tax/0008218", -15000000))
        assert role == "tax_payment"
        assert "keyword_match" in reason

    def test_kra_paye_debit(self):
        role, reason = classify_with_reason(txn("kra paye deduction march 2025", -1800000))
        assert role == "tax_payment"
        assert "keyword_match" in reason

    def test_kra_withholding_debit(self):
        role, reason = classify_with_reason(txn("kra withholding tax", -3500000))
        assert role == "tax_payment"
        assert "keyword_match" in reason

    def test_vat_remittance_debit(self):
        role, reason = classify_with_reason(txn("vat remittance march 2025", -8000000))
        assert role == "tax_payment"
        assert "keyword_match" in reason

    def test_kra_reversal_credit_not_tax_payment(self):
        """KRA reversal (credit) must NOT be tax_payment."""
        role, _ = classify_with_reason(txn("reversal credit kra tax", 15000000))
        assert role != "tax_payment"

    def test_kra_credit_large_needs_review(self):
        """Unexpected large credit from KRA → needs_review."""
        role, _ = classify_with_reason(txn("credit from kra", 10000000))
        assert role == "needs_review"

    def test_kra_tax_refund_credit_not_tax_payment(self):
        """KRA refund (credit) must NOT be tax_payment."""
        role, _ = classify_with_reason(txn("kra tax refund overpayment", 5000000))
        assert role != "tax_payment"


# ── BANK TO MOBILE & EAZZY-FUNDS ────────────────────────────────────────────

def test_bank_to_mobile_debit_supplier():
    role, reason = classify_with_reason(txn("bank to mobile 254712469888-mr nyoike re", -4500000))
    assert role == "supplier"
    assert "bank_to_mobile_outflow" in reason

def test_bank_to_mobile_credit_supplier():
    """Bank-to-mobile with positive amount (reversal/unusual) still classified as supplier."""
    role, reason = classify_with_reason(txn("bank to mobile 254711348938-fuel payment", 5000000))
    assert role == "supplier"
    assert "bank_to_mobile_outflow" in reason

def test_eazzy_funds_credit_revenue():
    role, reason = classify_with_reason(txn("eazzy-funds trnsf frm 101600023751 s2858", 11200000))
    assert role == "revenue_operational"
    assert "eazzy_funds_inflow" in reason

def test_eazzy_funds_debit_supplier():
    role, reason = classify_with_reason(txn("eazzy-funds trnsf to 101600023751", -5000000))
    assert role == "supplier"
    assert "eazzy_funds_outflow" in reason

def test_eazzy_funds_zero_amount_supplier():
    """EAZZY-FUNDS with zero amount — keyword matches, non-positive falls to supplier."""
    role, reason = classify_with_reason(txn("eazzy-funds trnsf frm 101714684333 borny", 0))
    assert role == "supplier"
    assert "eazzy_funds_outflow" in reason

def test_payed_flixnet_revenue():
    """PAYED with number prefix (not 'PAYED BY') still classified as revenue."""
    role, reason = classify_with_reason(txn("payed 703193140089 by:flixnet/7891234", 500000))
    assert role == "revenue_operational"
    assert "payed_by_prefix" in reason


# ── LOAN KEYWORD EXPANSIONS ───────────────────────────────────────────────────

def test_od_limit_credit_loan_inflow():
    """'od limit' credit → loan_inflow (new keyword, no loan substring)."""
    role, reason = classify_with_reason(txn("od limit approved equity bank", 500000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_stawi_credit_loan_inflow():
    """Safaricom Stawi mobile credit → loan_inflow."""
    role, reason = classify_with_reason(txn("stawi credit safaricom 254722000001", 200000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_zidisha_credit_loan_inflow():
    """Zidisha peer-lending disbursement → loan_inflow."""
    role, reason = classify_with_reason(txn("zidisha loan disbursement ref 20251101", 1500000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_mshwari_credit_loan_inflow():
    """M-Shwari credit facility → loan_inflow."""
    role, reason = classify_with_reason(txn("mshwari loan credited to account", 300000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_kcb_mpesa_credit_loan_inflow():
    """KCB M-PESA loan disbursement → loan_inflow."""
    role, reason = classify_with_reason(txn("kcb m-pesa loan credit 0712345678", 1000000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_jiinue_credit_loan_inflow():
    """Equity Bank Jiinue product credit → loan_inflow."""
    role, reason = classify_with_reason(txn("jiinue credit equity bank limited", 750000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_jiendeleze_credit_loan_inflow():
    """Equity Bank Jiendeleze product credit → loan_inflow."""
    role, reason = classify_with_reason(txn("jiendeleze disbursement equity bank", 2000000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_jiinue_repayment_debit_loan_repayment():
    """Jiinue repayment debit → loan_repayment (Buildex regression guard)."""
    role, reason = classify_with_reason(txn("jiinue repayment equity bank", -400000))
    assert role == "loan_repayment"
    assert "keyword_match" in reason

def test_overdraft_repayment_debit_loan_repayment():
    """'overdraft repayment' debit → loan_repayment (no loan substring in phrase)."""
    role, reason = classify_with_reason(txn("overdraft repayment equity bank march", -850000))
    assert role == "loan_repayment"
    assert "keyword_match" in reason

def test_od_repayment_debit_loan_repayment():
    """'od repayment' debit → loan_repayment."""
    role, reason = classify_with_reason(txn("od repayment ref 20250301 kcb", -300000))
    assert role == "loan_repayment"
    assert "keyword_match" in reason

def test_od_recovery_debit_loan_repayment():
    """'od recovery' debit → loan_repayment."""
    role, reason = classify_with_reason(txn("od recovery automatic debit equity", -620000))
    assert role == "loan_repayment"
    assert "keyword_match" in reason

def test_payloan_credit_loan_inflow():
    """'payloan' hits 'loan' substring → loan_inflow on credit (already covered, regression guard)."""
    role, reason = classify_with_reason(txn("payloan 254700000001 drawdown", 1000000))
    assert role == "loan_inflow"
    assert "keyword_match" in reason

def test_tendepay_debit_needs_review():
    """TENDEPAY LIMITED debits (Buildex KCB + Equity) → needs_review, not loan_repayment
    (PAR-237: TendePay is a CBK-licensed payment platform, not a lender)."""
    role, reason = classify_with_reason(txn("transfer 107853 tendepay limited", -200000000))
    assert role == "needs_review"
    assert "tendepay" in reason

def test_tendepay_ltd_debit_needs_review():
    """TENDEPAY LTD variant (Equity RTGS descriptor) → needs_review, not loan_repayment
    (PAR-237: TendePay is a CBK-licensed payment platform, not a lender)."""
    role, reason = classify_with_reason(txn("rtgs: rtobzn04308434 tendepay ltd", -15000000))
    assert role == "needs_review"
    assert "tendepay" in reason

def test_swift_charge_jiinue_bank_charge():
    """SWIFT charge on Jiinue RTGS → bank_charge, not loan_repayment (lender name must not win)."""
    role, reason = classify_with_reason(txn("swift charge jiinue loan funds ref 20250315", -575))
    assert role == "bank_charge"
    assert "swift_charge_fee" in reason

def test_swift_charge_generic_bank_charge():
    """Any 'swift charge' descriptor → bank_charge regardless of other content."""
    role, reason = classify_with_reason(txn("swift charge outward wire ref xyz", -2500))
    assert role == "bank_charge"
    assert "swift_charge_fee" in reason

