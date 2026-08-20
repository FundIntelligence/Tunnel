"""
PAR-189 Stage 6 verification — Tax Payment Pattern extraction into
build_snapshot_context().

Same pattern as Stages 1-5: the real acceptance bar is a byte-diff of
render_snapshot_html()'s HTML output on the real Deed document, old path vs
new. This file verifies the presentation dict (tax_count/tax_freq_str/
tax_penalty_count/tax_jan_spike_str/tax_total_str/tax_note) is byte-identical
between the ORIGINAL inline computation (transcribed verbatim from the
pre-Stage-6 source, i.e. PR #161-#165's merged state,
snapshot_html_renderer.py lines 576-591 + 939-960) and the NEW
build_snapshot_context() + adapter path — including the two quirks flagged in
TaxPaymentPattern's docstring: (1) this section's role filter is
role == "tax_payment" ONLY, unlike Tax Compliance Analysis's _TAX_ROLES
(which also matches "kra_payment"); (2) jan_spike (drives narrative) and
jan_spike_total's presence (drives whether the January row renders at all)
are two separately-computed conditions, not one derived from the other. The
real-document diff is run separately and is the actual acceptance-bar
evidence.
"""
from __future__ import annotations

from collections import defaultdict

import pytest

from v1.analysis.snapshot_context import _build_tax_payment_pattern
from v1.analysis.snapshot_html_renderer import _tax_payment_pattern_ctx_from


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-6 source
# (backend/v1/analysis/snapshot_html_renderer.py as merged through PR #165).
# ─────────────────────────────────────────────────────────────────────────────

def _original_tax_payment_pattern(txns):
    tax_txns = [t for t in txns if t["role"] == "tax_payment" and t["signed"] < 0]
    tax_by_month = defaultdict(lambda: {"count": 0, "total": 0})
    for t in tax_txns:
        m = (t["txn_date"] or "")[:7]
        tax_by_month[m]["count"] += 1
        tax_by_month[m]["total"] += t["abs"]
    jan_spike = any(m.endswith("-01") for m in tax_by_month)
    penalty_count = sum(
        1 for t in tax_txns
        if any(k in (t["desc"] or "").upper() for k in ("PENALTY", "PENALT", "SURCHARGE", "FINE"))
    )
    tax_total_cents = sum(t["abs"] for t in tax_txns)
    tax_months_count = len(tax_by_month)
    jan_month = next((m for m in tax_by_month if m.endswith("-01")), None)
    jan_total = tax_by_month[jan_month]["total"] if jan_month else 0

    tax_freq_str = (
        f"{len(tax_txns) / tax_months_count:.1f} / month" if tax_months_count > 0 else "--"
    )
    tax_jan_spike_str = _fmt_kes(jan_total) if jan_total > 0 else ""
    if jan_spike and penalty_count == 0:
        tax_note = (
            "Consistent KRA cadence observed across all months. "
            "January spike consistent with prior-year settlement — not a penalty indicator. "
            "Regular PAYE + VAT cadence maintained. "
            "Note: Bank payment regularity observed, not compliance status. Verify certificate independently."
        )
    elif penalty_count > 0:
        tax_note = (
            f"{penalty_count} potential penalty transaction(s) detected — "
            "verify KRA compliance certificate independently."
        )
    else:
        tax_note = (
            "Regular KRA payment pattern observed. "
            "Note: Bank regularity only — verify compliance certificate independently."
        )

    return {
        "tax_count":         len(tax_txns),
        "tax_freq_str":      tax_freq_str,
        "tax_penalty_count": penalty_count,
        "tax_jan_spike_str": tax_jan_spike_str,
        "tax_total_str":     _fmt_kes(tax_total_cents),
        "tax_note":          tax_note,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _t(role, signed, txn_date, desc="", abs_cents=None):
    return {
        "role": role,
        "signed": signed,
        "abs": abs_cents if abs_cents is not None else abs(signed),
        "desc": desc,
        "txn_date": txn_date,
    }


SCENARIOS = [
    pytest.param([], id="empty_no_tax_txns"),
    pytest.param(
        [_t("tax_payment", -50000, "2026-03-15")],
        id="single_month_no_spike_no_penalty",
    ),
    pytest.param(
        [
            _t("tax_payment", -50000, "2026-01-15"),
            _t("tax_payment", -60000, "2026-02-15"),
        ],
        id="january_spike_no_penalty",
    ),
    pytest.param(
        [
            _t("tax_payment", -50000, "2026-01-15"),
            _t("tax_payment", -20000, "2026-01-20", desc="KRA PENALTY CHARGE"),
        ],
        id="january_spike_and_penalty_penalty_branch_wins",
    ),
    pytest.param(
        [_t("tax_payment", -50000, "2026-05-15", desc="late surcharge fee")],
        id="penalty_keyword_lowercase_still_matches",
    ),
    pytest.param(
        [
            _t("tax_payment", -10000, "2026-04-01"),
            _t("tax_payment", -10000, "2026-05-01"),
            _t("tax_payment", -10000, "2026-06-01"),
        ],
        id="multi_month_frequency_averages",
    ),
    pytest.param(
        [_t("tax_payment", 50000, "2026-01-15")],
        id="positive_signed_tax_payment_excluded",
    ),
    pytest.param(
        [_t("kra_payment", -50000, "2026-01-15")],
        id="kra_payment_role_excluded_unlike_tax_compliance",
    ),
    pytest.param(
        [
            _t("tax_payment", -50000, "2026-01-15"),
            _t("supplier", -999999, "2026-01-15"),
        ],
        id="non_tax_roles_ignored",
    ),
    pytest.param(
        [_t("tax_payment", -1, "2026-01-15", abs_cents=0)],
        id="zero_amount_january_txn_jan_spike_true_but_no_spike_row",
    ),
]


@pytest.mark.parametrize("txns", SCENARIOS)
def test_tax_payment_pattern_matches_original(txns):
    old = _original_tax_payment_pattern(txns)
    new_typed = _build_tax_payment_pattern(txns)
    new = _tax_payment_pattern_ctx_from(new_typed)
    assert new == old, f"Tax Payment Pattern diverged.\nOLD: {old}\nNEW: {new}"


def test_zero_amount_january_txn_diverges_jan_spike_from_jan_spike_total():
    """
    Locks in the Stage 6 fidelity finding documented on TaxPaymentPattern:
    jan_spike (drives narrative) and jan_spike_total (drives whether the
    January row renders) are separately computed. A zero-amount January tax
    transaction makes jan_spike True (a January-dated tax txn exists) while
    jan_spike_total stays None (the row-suppression check is jan_total > 0,
    and 0 is not > 0) -- and yet the narrative still takes the "spike, no
    penalty" branch because that branch keys off jan_spike, not the amount.
    """
    txns = [_t("tax_payment", -1, "2026-01-10", abs_cents=0)]
    typed = _build_tax_payment_pattern(txns)
    assert typed.jan_spike is True
    assert typed.jan_spike_total is None
    ctx = _tax_payment_pattern_ctx_from(typed)
    assert ctx["tax_jan_spike_str"] == ""
    assert ctx["tax_note"].startswith("Consistent KRA cadence observed")


def test_avg_per_month_is_none_when_no_tax_months():
    typed = _build_tax_payment_pattern([])
    assert typed.avg_per_month is None
    assert _tax_payment_pattern_ctx_from(typed)["tax_freq_str"] == "--"
