"""
PAR-189 Stage 10 verification — Monthly Cashflow extraction into
build_snapshot_context().

Same pattern as Stages 1-9: the real acceptance bar is a full-document
byte-diff of render_snapshot_html()'s output on the real Deed document (run
separately; PASS, byte-identical, reported on PAR-189).

Deed only exercises the multi-month, net-negative/declining-trend branch of
this section (confirmed by grepping its rendered output). The other branches
— all-positive, stable trend, single month, zero months — were checked
against real prod data directly (9 real snapshot rows across 7 distinct
deal_ids, all landing on the same negative/declining branch as Deed — see
the Stage 10 report) rather than assumed reachable. These fixtures cover the
branch matrix real data happened not to reach, same as Stage 9's precedent
for 4-Point Reconciliation.
"""
from __future__ import annotations

from v1.analysis.snapshot_context import (
    CashflowMonthRow,
    Money,
    MonthlyCashflow,
    Percent,
    _build_monthly_cashflow,
)
from v1.analysis.snapshot_html_renderer import MONTH_ABBR, _fmt_kes, _monthly_cashflow_ctx_from
from v1.analytics import monthly_cashflow as _monthly_cashflow


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-10 source
# (snapshot_html_renderer.py as merged at 4d3b821).
# ─────────────────────────────────────────────────────────────────────────────

def _original(monthly_merged, in_active_period):
    period_months = sorted(m for m in monthly_merged if in_active_period(m))
    neg_months = sorted(
        m for m in period_months
        if (monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"]) < 0
    )
    if neg_months:
        worst = min(
            neg_months,
            key=lambda m: monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"],
        )
        cashflow_note = (
            f"{len(neg_months)} of {len(period_months)} months net-negative. "
            f"Largest deficit in {MONTH_ABBR.get(worst[5:7], worst[5:7])} {worst[:4]}."
        )
    elif period_months:
        cashflow_note = f"All {len(period_months)} months net-positive."
    else:
        cashflow_note = "No cashflow data available."

    if len(period_months) < 2:
        cashflow_trend_note = (
            "Only one month of data is available — a trend cannot yet be established."
            if period_months else ""
        )
        cashflow_peak_trough_note = ""
    else:
        nets_by_month = {
            m: monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"]
            for m in period_months
        }
        trough_month = min(nets_by_month, key=lambda m: nets_by_month[m])
        peak_month = max(nets_by_month, key=lambda m: nets_by_month[m])
        first_net = nets_by_month[period_months[0]]
        last_net = nets_by_month[period_months[-1]]
        if last_net > first_net:
            trend_clause = "The trend over the observed period is net POSITIVE."
        elif last_net < first_net:
            trend_clause = "The trend over the observed period is net NEGATIVE — recent months show declining net position."
        else:
            trend_clause = "Net position is broadly stable with no clear directional trend."
        cashflow_peak_trough_note = (
            f"Trough of {_fmt_kes(nets_by_month[trough_month])} in "
            f"{MONTH_ABBR.get(trough_month[5:7], trough_month[5:7])} {trough_month[:4]}; "
            f"peak of {_fmt_kes(nets_by_month[peak_month])} in "
            f"{MONTH_ABBR.get(peak_month[5:7], peak_month[5:7])} {peak_month[:4]}."
        )
        cashflow_trend_note = trend_clause

    active_months = period_months
    max_abs_net = (
        max(abs(monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"])
            for m in active_months)
        if active_months else 1
    ) or 1
    rows = []
    for m in active_months:
        v = monthly_merged[m]
        net = v["inflow_cents"] - v["outflow_cents"]
        abs_net = abs(net)
        bar_pct = min(int(abs_net / max_abs_net * 100), 100)
        sign = "+" if net >= 0 else "−"
        rows.append({
            "month_label": MONTH_ABBR.get(m[5:7], m[5:7]),
            "inflow_str": f"{v['inflow_cents'] / 100:,.0f}",
            "outflow_str": f"{v['outflow_cents'] / 100:,.0f}",
            "net_str": f"{sign}{abs_net / 100:,.0f}",
            "net_color_class": "pos" if net >= 0 else "neg",
            "positive": net >= 0,
            "bar_pct": bar_pct,
        })
    return {
        "cashflow_note": cashflow_note,
        "cashflow_trend_note": cashflow_trend_note,
        "cashflow_peak_trough_note": cashflow_peak_trough_note,
        "cashflow_rows_ctx": rows,
    }


def _txn(month: str, day: str, cents: int, role: str = "revenue_operational") -> dict:
    return {
        "role": role,
        "amount_cents": cents,
        "txn_date": f"{month}-{day}",
        "txn_id": f"{month}-{day}-{cents}",
    }


def _assert_equiv(canon_tagged, in_active_period=lambda m: True, currency="KES"):
    monthly_merged = {
        row["month"]: {"inflow_cents": row["inflow_cents"], "outflow_cents": row["outflow_cents"]}
        for row in _monthly_cashflow(canon_tagged)
    }
    original = _original(monthly_merged, in_active_period)
    new = _monthly_cashflow_ctx_from(
        _build_monthly_cashflow(canon_tagged, in_active_period, currency)
    )
    assert new == original
    return new


# ─────────────────────────────────────────────────────────────────────────────
# Zero months — the "No cashflow data available." branch
# ─────────────────────────────────────────────────────────────────────────────

def test_zero_months_yields_no_data_note_and_no_rows():
    ctx = _assert_equiv([])
    assert ctx["cashflow_note"] == "No cashflow data available."
    assert ctx["cashflow_trend_note"] == ""
    assert ctx["cashflow_peak_trough_note"] == ""
    assert ctx["cashflow_rows_ctx"] == []


def test_zero_months_via_in_active_period_filtering_everything_out():
    canon_tagged = [_txn("2025-01", "05", 100_00)]
    ctx = _assert_equiv(canon_tagged, in_active_period=lambda m: False)
    assert ctx["cashflow_note"] == "No cashflow data available."


# ─────────────────────────────────────────────────────────────────────────────
# Single month — the "Only one month..." branch, no peak/trough
# ─────────────────────────────────────────────────────────────────────────────

def test_single_month_gets_caveat_not_trend_clause():
    canon_tagged = [
        _txn("2025-01", "05", 500_00),
        _txn("2025-01", "10", -200_00),
    ]
    ctx = _assert_equiv(canon_tagged)
    assert ctx["cashflow_trend_note"] == (
        "Only one month of data is available — a trend cannot yet be established."
    )
    assert ctx["cashflow_peak_trough_note"] == ""
    assert len(ctx["cashflow_rows_ctx"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Multi-month — all-positive, net-negative, and stable trend branches
# ─────────────────────────────────────────────────────────────────────────────

def test_all_positive_months_note_and_positive_trend():
    canon_tagged = [
        _txn("2025-01", "05", 500_00),
        _txn("2025-02", "05", 600_00),
        _txn("2025-03", "05", 900_00),
    ]
    ctx = _assert_equiv(canon_tagged)
    assert ctx["cashflow_note"] == "All 3 months net-positive."
    assert ctx["cashflow_trend_note"] == "The trend over the observed period is net POSITIVE."
    assert "Trough of" in ctx["cashflow_peak_trough_note"]
    assert all(r["positive"] for r in ctx["cashflow_rows_ctx"])


def test_mixed_months_note_names_largest_deficit_and_negative_trend():
    canon_tagged = [
        _txn("2025-01", "05", 500_00),
        _txn("2025-02", "05", -300_00),
        _txn("2025-03", "05", -900_00),
    ]
    ctx = _assert_equiv(canon_tagged)
    assert ctx["cashflow_note"] == "2 of 3 months net-negative. Largest deficit in Mar 2025."
    assert "NEGATIVE" in ctx["cashflow_trend_note"]


def test_stable_trend_when_first_and_last_net_equal():
    canon_tagged = [
        _txn("2025-01", "05", 400_00),
        _txn("2025-02", "05", -100_00),
        _txn("2025-03", "05", 400_00),
    ]
    ctx = _assert_equiv(canon_tagged)
    assert ctx["cashflow_trend_note"] == (
        "Net position is broadly stable with no clear directional trend."
    )


# ─────────────────────────────────────────────────────────────────────────────
# bar_pct — int() truncation preserved, not round() (the Stage 8/9 bug class)
# ─────────────────────────────────────────────────────────────────────────────

def test_bar_pct_truncates_like_the_original_not_rounds():
    # month A net = 999 (abs), month B net = 1000 (abs, the period max).
    # ratio = 999/1000 = 0.999 -> int(99.9) == 99, round(99.9) == 100.
    # If the new path ever switched to round(), this would silently render 100
    # instead of 99 -- exactly the digit-shift class of bug Stage 8 found and
    # Stage 9 generalised. Assert the exact int, not just equivalence with the
    # original (equivalence alone wouldn't distinguish a shared regression).
    canon_tagged = [
        _txn("2025-01", "05", 999_00),
        _txn("2025-02", "05", -1000_00),
    ]
    ctx = _assert_equiv(canon_tagged)
    rows_by_month = {r["month_label"]: r for r in ctx["cashflow_rows_ctx"]}
    assert rows_by_month["Jan"]["bar_pct"] == 99
    assert rows_by_month["Feb"]["bar_pct"] == 100


def test_bar_share_percent_is_a_0_1_fraction_not_already_multiplied():
    canon_tagged = [
        _txn("2025-01", "05", 999_00),
        _txn("2025-02", "05", -1000_00),
    ]
    mc = _build_monthly_cashflow(canon_tagged, lambda m: True, "KES")
    for row in mc.rows:
        assert isinstance(row.bar_share, Percent)
        assert 0.0 <= row.bar_share.value <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Schema conventions — typed Money, no CSS/color in the dataclass
# ─────────────────────────────────────────────────────────────────────────────

def test_rows_carry_typed_money_not_raw_ints():
    canon_tagged = [
        _txn("2025-01", "05", 500_00),
        _txn("2025-02", "05", -300_00),
    ]
    mc = _build_monthly_cashflow(canon_tagged, lambda m: True, "KES")
    assert isinstance(mc, MonthlyCashflow)
    for row in mc.rows:
        assert isinstance(row, CashflowMonthRow)
        assert isinstance(row.inflow, Money)
        assert isinstance(row.outflow, Money)
        assert isinstance(row.net, Money)
        assert row.inflow.currency == "KES"


def test_dataclass_carries_no_css_class_or_color_fields():
    mc = _build_monthly_cashflow(
        [_txn("2025-01", "05", 100_00)], lambda m: True, "KES",
    )
    row = mc.rows[0]
    row_fields = set(row.__dataclass_fields__.keys())
    assert not (row_fields & {"net_color_class", "color", "css_class"})


def test_currency_propagates_from_deal_not_hardcoded():
    canon_tagged = [_txn("2025-01", "05", 100_00), _txn("2025-02", "05", 100_00)]
    mc = _build_monthly_cashflow(canon_tagged, lambda m: True, "USD")
    assert mc.rows[0].inflow.currency == "USD"
