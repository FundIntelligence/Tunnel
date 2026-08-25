"""
PAR-189 Stage 11 verification — Key Metrics and Observed Patterns extraction
into build_snapshot_context(). This is the last stage: every section
render_snapshot_html() renders is now covered by build_snapshot_context() or
genuinely needs no extraction (the locked reconciliation section, per the
Stage 9 report).

Same pattern as Stages 1-10: the real acceptance bar is a full-document
byte-diff of render_snapshot_html()'s output on the real Deed document (run
separately; PASS, byte-identical, reported on PAR-189).

Both sections were checked for real inbound coupling before picking (per
task instruction) and found independently extractable — neither reads the
other's finished dataclass output, only shared raw aggregates each
recomputes for itself (same accepted-duplication pattern as every prior
stage). Landed together in one stage because this is explicitly the last
one, not because either was blocked on the other.

Deed (no audited financials) only exercises: Key Metrics' NOT-available
branch (Income quality / Loan obligations / Cash trend-unavailable), and
Observed Patterns' "Tax payment gap" + "Net-negative months" cards. The
untested branches were checked against real prod data directly (see the
Stage 11 report):
  - Key Metrics' available=True branch (PBT margin/loan variance/revenue
    gap): driven against real af values (13 real deals share one audited-
    financials template) + a real deal's canon_tagged.
  - Observed Patterns "Irregular payroll": fires correctly on 8 real deals
    (4/13, 1/12 payroll-month ratios).
  - Observed Patterns "Analyst classification pending": fires correctly on
    a real deal with 463 real needs_review transactions.
  - Observed Patterns "M-Pesa concentration" and Key Metrics' Cash Trend
    real-balance branch: confirmed UNREACHABLE by any current real prod
    deal (SQL sweep — no deal has mpesa_pct anywhere near 40%; every raw
    transaction in prod currently has balance_cents = NULL). Fixture-only,
    flagged explicitly rather than silently left untested.
"""
from __future__ import annotations

from v1.analysis.snapshot_context import (
    CashTrend,
    KeyMetrics,
    KeyMetricsConfig,
    Money,
    ObservedPattern,
    ObservedPatterns,
    Percent,
    _build_key_metrics,
    _build_observed_patterns,
)
from v1.analysis.snapshot_html_renderer import (
    _fmt_pct_1dp,
    _key_metrics_ctx_from,
    _observed_patterns_ctx_from,
)


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-11 source
# (snapshot_html_renderer.py as merged at 8710348).
# ─────────────────────────────────────────────────────────────────────────────

_MONTH_ABBR = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}
_REVENUE_ROLES = {"revenue_operational", "mpesa_inflow", "pesalink_inflow"}
_CASHFLOW_INFLOW_ROLES = {"revenue_operational", "mpesa_inflow", "pesalink_inflow", "other_inflow"}


def _fmt_kes_compact(cents: int) -> str:
    kes = cents / 100
    if kes >= 1_000_000:
        return f"{kes / 1_000_000:.1f}M"
    if kes >= 1_000:
        return f"{kes / 1_000:.0f}K"
    return f"{kes:,.0f}"


def _original_key_metrics(txns, canon_tagged, in_active_period, recon_available, af, recon_section, currency):
    by_month_rev = {}
    for t in txns:
        if t["signed"] > 0 and t["role"] in _REVENUE_ROLES:
            m = (t["txn_date"] or "")[:7]
            if in_active_period(m):
                by_month_rev[m] = by_month_rev.get(m, 0) + t["signed"]
    avg_rev_cents = int(sum(by_month_rev.values()) / len(by_month_rev)) if by_month_rev else 0

    if recon_available:
        turnover_cents = int(af.get("turnover_cents") or 0)
        pbt_cents = int(af.get("profit_before_tax_cents") or 0)
        pbt_margin = (pbt_cents / turnover_cents * 100) if turnover_cents > 0 else 0
        fy = str(af.get("financial_year") or "")

        loans_r = recon_section.get("loan_activity") or {}
        loan_var_pct = loans_r.get("variance_pct")
        loan_var_str = f"{abs(loan_var_pct):.1f}% var" if loan_var_pct is not None else "0% var"

        rev_r = recon_section.get("revenue") or {}
        rev_gap = rev_r.get("gap_pct")
        rev_gap_str = f"{rev_gap:.1f}%" if rev_gap is not None else "--"

        return [
            {"label": "Avg monthly revenue", "value": _fmt_kes_compact(avg_rev_cents),
             "sub": f"{currency} · operational inflows", "color_class": ""},
            {"label": "PBT margin", "value": f"{pbt_margin:.2f}%",
             "sub": f"vs declared turnover · FY{fy}",
             "color_class": "positive" if pbt_margin > 0 else "negative"},
            {"label": "Loan reconciliation", "value": loan_var_str,
             "sub": f"{loans_r.get('status', '')} · Note 14", "color_class": "warning"},
            {"label": "Revenue gap", "value": rev_gap_str,
             "sub": "observed vs declared · accrual basis",
             "color_class": "warning" if (rev_gap or 0) > 15 else ""},
        ]

    by_role_in = {}
    total_in = 0
    for t in canon_tagged:
        if t["amount_cents"] > 0 and t["role"] in _CASHFLOW_INFLOW_ROLES:
            by_role_in[t["role"]] = by_role_in.get(t["role"], 0) + t["amount_cents"]
            total_in += t["amount_cents"]
    op_in = sum(v for k, v in by_role_in.items() if k in _REVENUE_ROLES)
    income_quality_pct = (op_in / total_in * 100) if total_in else 0

    repay_months = {}
    for t in txns:
        if t["role"] == "loan_repayment" and t["signed"] < 0:
            m = (t["txn_date"] or "")[:7]
            if in_active_period(m):
                repay_months[m] = repay_months.get(m, 0) + 1
    loan_freq = sum(repay_months.values()) / len(repay_months) if repay_months else 0
    loan_repayment_txn_count = sum(1 for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0)

    bal_txns = sorted(
        [t for t in txns if t.get("balance") is not None],
        key=lambda x: x["txn_date"] or "",
    )
    if bal_txns:
        first_bal = bal_txns[0]["balance"]
        last_bal = bal_txns[-1]["balance"]
        yoy_pct = ((last_bal - first_bal) / abs(first_bal) * 100) if first_bal else None
        cash_trend_str = f"{yoy_pct:+.1f}%" if yoy_pct is not None else "--"
        cash_trend_sub = f"{currency} {first_bal/100:,.0f} → {last_bal/100:,.0f} YoY"
    else:
        cash_trend_str = "--"
        cash_trend_sub = "balance data unavailable"

    return [
        {"label": "Avg monthly revenue", "value": _fmt_kes_compact(avg_rev_cents),
         "sub": f"{currency} · operational inflows", "color_class": ""},
        {"label": "Income quality", "value": f"{income_quality_pct:.1f}%",
         "sub": "operational vs total inflows",
         "color_class": "positive" if income_quality_pct >= 70 else "warning"},
        {"label": "Loan obligations", "value": f"{loan_freq:.1f}/mo",
         "sub": f"repayments · {loan_repayment_txn_count} txns detected", "color_class": "warning"},
        {"label": "Cash trend", "value": cash_trend_str, "sub": cash_trend_sub,
         "color_class": "positive" if cash_trend_str.startswith("+") else "warning"},
    ]


def _original_observed_patterns(txns, canon_tagged, in_active_period, credit_scoring_inputs_list):
    _TAG_CLASS = {"Watch": "t-wat", "Observed": "t-chk", "Pattern": "t-pat", "Coverage": "t-chk"}
    _ITEM_CLASS = {"Watch": "watch", "Observed": "check", "Pattern": "pattern", "Coverage": "check"}

    by_role_in = {}
    total_in = 0
    for t in canon_tagged:
        if t["amount_cents"] > 0 and t["role"] in _CASHFLOW_INFLOW_ROLES:
            by_role_in[t["role"]] = by_role_in.get(t["role"], 0) + t["amount_cents"]
            total_in += t["amount_cents"]
    mpesa_cents = by_role_in.get("mpesa_inflow", 0)
    mpesa_pct = (mpesa_cents / total_in * 100) if total_in else 0

    from v1.analytics import monthly_cashflow as _mc
    monthly_merged = {
        row["month"]: {"inflow_cents": row["inflow_cents"], "outflow_cents": row["outflow_cents"]}
        for row in _mc(canon_tagged)
    }
    period_months = sorted(m for m in monthly_merged if in_active_period(m))
    neg_months = sorted(
        m for m in period_months
        if (monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"]) < 0
    )

    all_months_active = set()
    payroll_months_active = set()
    for t in txns:
        m = (t["txn_date"] or "")[:7]
        if t["txn_date"] and in_active_period(m):
            all_months_active.add(m)
            if t["role"] == "payroll":
                payroll_months_active.add(m)
    n_total_months = len(all_months_active)
    n_payroll_months = len(payroll_months_active)
    if n_total_months == 0 or n_payroll_months == 0:
        payroll_stability_live = "NOT_DETECTED"
    elif n_payroll_months == n_total_months:
        payroll_stability_live = "CONSISTENT"
    elif n_payroll_months >= n_total_months * 8 // 10:
        payroll_stability_live = "MOSTLY_CONSISTENT"
    else:
        payroll_stability_live = "IRREGULAR"

    needs_review_count = sum(1 for t in txns if t["role"] == "needs_review")

    patterns = []
    if mpesa_pct > 40:
        tag = "Watch"
        patterns.append({
            "name": "M-Pesa concentration", "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"M-Pesa inflows represent {mpesa_pct:.1f}% of total observed inflows",
            "check_prompt": "→ Review: consistent with declared customer mix and B2B model?",
        })
    for cs in credit_scoring_inputs_list:
        if cs.get("kra_compliance") == "GAPS_DETECTED":
            tag = "Observed"
            patterns.append({
                "name": "Tax payment gap", "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
                "data_statement": cs.get("kra_note") or "Tax payment gaps detected",
                "check_prompt": "→ Review: gap months explained by filing schedule or missed payments?",
            })
            break
    if payroll_stability_live == "IRREGULAR":
        tag = "Pattern"
        patterns.append({
            "name": "Irregular payroll", "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"Payroll detected in {n_payroll_months} of {n_total_months} months",
            "check_prompt": "→ Review: casual workforce or payroll routed off-statement?",
        })
    if len(neg_months) > 2:
        label_months = ", ".join(_MONTH_ABBR.get(m[5:7], m[5:7]) for m in neg_months[:3]) + ("..." if len(neg_months) > 3 else "")
        tag = "Pattern"
        patterns.append({
            "name": "Net-negative months", "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"{len(neg_months)} of {len(period_months)} months net-negative: {label_months}",
            "check_prompt": "→ Review: seasonal pattern or sustained cash drain?",
        })
    if needs_review_count > 100:
        tag = "Coverage"
        patterns.append({
            "name": "Analyst classification pending", "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"{needs_review_count} transactions flagged needs_review",
            "check_prompt": "→ Review: resolve in Parity dashboard before finalising snapshot.",
        })
    return patterns[:5]


def _txn(month: str, day: str, cents: int, role: str) -> dict:
    return {"txn_date": f"{month}-{day}", "signed": cents, "role": role, "balance": None}


def _canon(month: str, day: str, cents: int, role: str) -> dict:
    return {"txn_date": f"{month}-{day}", "amount_cents": cents, "role": role, "txn_id": f"{month}-{day}-{cents}-{role}"}


def _assert_km_equiv(txns, canon_tagged, in_active_period=lambda m: True, recon_available=False,
                      af=None, recon_section=None, currency="KES"):
    af = af or {}
    recon_section = recon_section or {}
    original = _original_key_metrics(txns, canon_tagged, in_active_period, recon_available, af, recon_section, currency)
    new = _key_metrics_ctx_from(
        _build_key_metrics(txns, canon_tagged, in_active_period, recon_available, af, recon_section, currency)
    )
    assert new == original
    return new


def _assert_op_equiv(txns, canon_tagged, in_active_period=lambda m: True, credit_scoring_inputs_list=None):
    credit_scoring_inputs_list = credit_scoring_inputs_list or []
    original = _original_observed_patterns(txns, canon_tagged, in_active_period, credit_scoring_inputs_list)
    new = _observed_patterns_ctx_from(
        _build_observed_patterns(txns, canon_tagged, in_active_period, credit_scoring_inputs_list)
    )
    assert new == original
    return new


# ─────────────────────────────────────────────────────────────────────────────
# Key Metrics — not-available (observed-only) branch
# ─────────────────────────────────────────────────────────────────────────────

def test_km_not_available_income_quality_and_loan_obligations():
    txns = [
        _txn("2025-01", "05", 500_00, "revenue_operational"),
        _txn("2025-01", "10", -100_00, "loan_repayment"),
        _txn("2025-02", "05", -100_00, "loan_repayment"),
    ]
    canon_tagged = [_canon("2025-01", "05", 500_00, "revenue_operational")]
    ctx = _assert_km_equiv(txns, canon_tagged)
    assert ctx[1]["label"] == "Income quality"
    assert ctx[2]["label"] == "Loan obligations"
    assert ctx[2]["value"] == "1.0/mo"


def test_km_not_available_cash_trend_unavailable_no_balance_data():
    ctx = _assert_km_equiv([], [])
    cash_cell = ctx[3]
    assert cash_cell["value"] == "--"
    assert cash_cell["sub"] == "balance data unavailable"
    assert cash_cell["color_class"] == "warning"


def test_km_cash_trend_real_balance_data_positive():
    txns = [
        {"txn_date": "2025-01-01", "signed": 0, "role": "other", "balance": 100_00},
        {"txn_date": "2025-06-01", "signed": 0, "role": "other", "balance": 150_00},
    ]
    ctx = _assert_km_equiv(txns, [])
    cash_cell = ctx[3]
    assert cash_cell["value"] == "+50.0%"
    assert cash_cell["color_class"] == "positive"


def test_km_cash_trend_first_balance_zero_shows_dash_but_real_sub():
    # Division-by-zero guard: balance data exists but opening balance is 0 --
    # headline is "--", sub-line still shows the real (0 -> X) balances.
    txns = [
        {"txn_date": "2025-01-01", "signed": 0, "role": "other", "balance": 0},
        {"txn_date": "2025-06-01", "signed": 0, "role": "other", "balance": 500_00},
    ]
    ctx = _assert_km_equiv(txns, [])
    cash_cell = ctx[3]
    assert cash_cell["value"] == "--"
    assert "0 →" in cash_cell["sub"]


def test_km_income_quality_high_threshold_uses_config():
    canon_tagged = [_canon("2025-01", "05", 1000_00, "revenue_operational")]
    km = _build_key_metrics([], canon_tagged, lambda m: True, False, {}, {}, "KES")
    assert km.income_quality_high is True
    assert km.income_quality.value == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Key Metrics — available (recon) branch, including the round-trip-bug checks
# ─────────────────────────────────────────────────────────────────────────────

def test_km_available_pbt_margin_and_revenue_gap():
    af = {"turnover_cents": 100_000_00, "profit_before_tax_cents": 12_345_00, "financial_year": 2025}
    recon_section = {
        "loan_activity": {"variance_pct": -8.25, "status": "VARIANCE"},
        "revenue": {"gap_pct": 22.5},
    }
    ctx = _assert_km_equiv([], [], recon_available=True, af=af, recon_section=recon_section)
    assert ctx[1]["value"] == "12.35%"
    assert ctx[1]["sub"] == "vs declared turnover · FY2025"
    assert ctx[2]["value"] == "8.2% var"  # abs(-8.25) at .1f -- Python round-half-to-even
    assert ctx[3]["value"] == "22.5%"
    assert ctx[3]["color_class"] == "warning"


def test_km_available_revenue_gap_negative_no_abs_no_warning():
    af = {"turnover_cents": 100_000_00, "profit_before_tax_cents": 0, "financial_year": 2025}
    recon_section = {"revenue": {"gap_pct": -3.4}}
    ctx = _assert_km_equiv([], [], recon_available=True, af=af, recon_section=recon_section)
    assert ctx[3]["value"] == "-3.4%"
    assert ctx[3]["color_class"] == ""


def test_km_available_loan_variance_none_falls_back_to_zero_var():
    af = {"turnover_cents": 0, "profit_before_tax_cents": 0, "financial_year": 2025}
    ctx = _assert_km_equiv([], [], recon_available=True, af=af, recon_section={})
    assert ctx[2]["value"] == "0% var"
    assert ctx[3]["value"] == "--"


def test_km_pbt_margin_zero_turnover_guard():
    af = {"turnover_cents": 0, "profit_before_tax_cents": 500_00, "financial_year": 2025}
    ctx = _assert_km_equiv([], [], recon_available=True, af=af, recon_section={})
    assert ctx[1]["value"] == "0.00%"
    assert ctx[1]["color_class"] == "negative"  # pbt_margin=0 -> not > 0 -> negative


def test_km_loan_variance_and_revenue_gap_are_the_precoverage_pct_1dp_bug_class():
    # Round-trip-bug audit: loan_variance/revenue_gap are sourced from
    # recon_section (pre-rounded upstream, same class as 4-Point
    # Reconciliation's variances) and MUST use _fmt_pct_1dp, not a plain
    # f-string on the round-tripped Percent -- verified by checking a value
    # that would diverge under the naive round-trip (per Stage 9's own
    # measured divergence set).
    recon_section = {"loan_activity": {"variance_pct": -177.7, "status": "VARIANCE"}}
    af = {"turnover_cents": 0, "profit_before_tax_cents": 0, "financial_year": 2025}
    km = _build_key_metrics([], [], lambda m: True, True, af, recon_section, "KES")
    assert km.loan_variance is not None
    rendered = _fmt_pct_1dp(km.loan_variance)
    assert rendered == "177.7"


def test_km_pbt_margin_is_live_computed_not_fmt_pct_1dp_class():
    # Counter-case (Stage 10/11 discipline): pbt_margin/income_quality/
    # cash_trend.yoy are live-computed, NOT pre-rounded upstream -- they
    # must NOT be routed through _fmt_pct_1dp (that would double-round a
    # value that was never rounded once). Confirmed by construction: the
    # ctx_from function formats km.pbt_margin.value*100 directly with
    # f"{...:.2f}", not _fmt_pct_1dp -- this test pins that by checking a
    # value with more than 2 significant decimal digits round-trips exactly.
    af = {"turnover_cents": 700_000_00, "profit_before_tax_cents": 100_000_00, "financial_year": 2025}
    ctx = _assert_km_equiv([], [], recon_available=True, af=af, recon_section={})
    # 100/700*100 = 14.2857142857...% -> .2f = "14.29%"
    assert ctx[1]["value"] == "14.29%"


# ─────────────────────────────────────────────────────────────────────────────
# Observed Patterns
# ─────────────────────────────────────────────────────────────────────────────

def test_op_empty_when_no_conditions_met():
    ctx = _assert_op_equiv([], [])
    assert ctx == []


def test_op_mpesa_concentration_fires_above_40_pct():
    canon_tagged = [
        _canon("2025-01", "05", 500_00, "mpesa_inflow"),
        _canon("2025-01", "06", 400_00, "revenue_operational"),
    ]
    ctx = _assert_op_equiv([], canon_tagged)
    names = [p["name"] for p in ctx]
    assert "M-Pesa concentration" in names


def test_op_tax_payment_gap_uses_first_gaps_detected_and_stops():
    cs_list = [
        {"kra_compliance": "PASS"},
        {"kra_compliance": "GAPS_DETECTED", "kra_note": "first gap note"},
        {"kra_compliance": "GAPS_DETECTED", "kra_note": "second gap note"},
    ]
    ctx = _assert_op_equiv([], [], credit_scoring_inputs_list=cs_list)
    gap = next(p for p in ctx if p["name"] == "Tax payment gap")
    assert gap["data_statement"] == "first gap note"


def test_op_irregular_payroll_fires_between_thresholds():
    txns = [
        _txn("2025-01", "01", 0, "payroll"),
        _txn("2025-02", "01", 0, "other"),
        _txn("2025-03", "01", 0, "other"),
    ]
    ctx = _assert_op_equiv(txns, [])
    irregular = next(p for p in ctx if p["name"] == "Irregular payroll")
    assert irregular["data_statement"] == "Payroll detected in 1 of 3 months"


def test_op_consistent_payroll_does_not_fire():
    txns = [_txn("2025-01", "01", 0, "payroll"), _txn("2025-02", "01", 0, "payroll")]
    ctx = _assert_op_equiv(txns, [])
    assert not any(p["name"] == "Irregular payroll" for p in ctx)


def test_op_net_negative_months_label_truncates_at_three():
    canon_tagged = [
        _canon("2025-01", "05", -100_00, "other"),
        _canon("2025-02", "05", -100_00, "other"),
        _canon("2025-03", "05", -100_00, "other"),
        _canon("2025-04", "05", -100_00, "other"),
        _canon("2025-05", "05", 100_00, "other"),
    ]
    ctx = _assert_op_equiv([], canon_tagged)
    neg = next(p for p in ctx if p["name"] == "Net-negative months")
    assert "..." in neg["data_statement"]
    assert neg["data_statement"].startswith("4 of 5 months net-negative: Jan, Feb, Mar...")


def test_op_analyst_classification_pending_fires_above_100():
    txns = [_txn("2025-01", str(d).zfill(2), 0, "needs_review") for d in range(1, 29)] * 4
    ctx = _assert_op_equiv(txns[:101], [])
    pending = next(p for p in ctx if p["name"] == "Analyst classification pending")
    assert pending["data_statement"] == "101 transactions flagged needs_review"


def test_op_capped_at_five_patterns():
    canon_tagged = [
        _canon("2025-01", "05", 500_00, "mpesa_inflow"),
        _canon("2025-01", "06", 400_00, "revenue_operational"),
        _canon("2025-02", "05", -100_00, "other"),
        _canon("2025-03", "05", -100_00, "other"),
        _canon("2025-04", "05", -100_00, "other"),
    ]
    txns = [
        _txn("2025-01", "01", 0, "payroll"),
        _txn("2025-02", "01", 0, "other"),
        _txn("2025-03", "01", 0, "other"),
    ] + [_txn("2025-01", str(d).zfill(2), 0, "needs_review") for d in range(1, 102)]
    cs_list = [{"kra_compliance": "GAPS_DETECTED", "kra_note": "gap"}]
    ctx = _assert_op_equiv(txns, canon_tagged, credit_scoring_inputs_list=cs_list)
    assert len(ctx) <= 5


# ─────────────────────────────────────────────────────────────────────────────
# Schema conventions — typed Money/Percent, no CSS/color in shared context
# ─────────────────────────────────────────────────────────────────────────────

def test_key_metrics_dataclass_carries_no_css_class_fields():
    km = _build_key_metrics([], [], lambda m: True, False, {}, {}, "KES")
    fields = set(km.__dataclass_fields__.keys())
    assert not (fields & {"color_class", "css_class"})
    assert isinstance(km.avg_monthly_revenue, Money)


def test_observed_pattern_dataclass_carries_no_css_class_fields():
    op = ObservedPattern(key="x", name="X", tag="Watch", data_statement="s", check_prompt="c")
    fields = set(op.__dataclass_fields__.keys())
    assert not (fields & {"tag_class", "item_class"})


def test_cash_trend_yoy_is_percent_type_when_present():
    txns = [
        {"txn_date": "2025-01-01", "signed": 0, "role": "other", "balance": 100_00},
        {"txn_date": "2025-06-01", "signed": 0, "role": "other", "balance": 150_00},
    ]
    km = _build_key_metrics(txns, [], lambda m: True, False, {}, {}, "KES")
    assert isinstance(km.cash_trend, CashTrend)
    assert isinstance(km.cash_trend.yoy, Percent)
