"""
PAR-189 Stage 2 verification — Transaction Pattern Analysis + Tax Compliance
Analysis extraction into build_snapshot_context().

Same caveat as Stage 1 (test_par189_shared_context_extraction.py): the real
acceptance bar is a byte-diff of render_snapshot_html()'s HTML output on the
real Deed document, old path vs new. This file verifies the two presentation
dicts (transaction_patterns_ctx, tax_compliance_ctx) are byte-identical
between the ORIGINAL inline computation (transcribed verbatim from the
pre-Stage-2 source, i.e. PR #161's already-verified state) and the NEW
build_snapshot_context() + adapter path, across fixture inputs chosen to hit
every branch. Per the template (snapshot.html:1356-1374), both dicts are
consumed with no further string formatting — so dict equality here implies
HTML equality for these two sections, for any input these dicts can
represent. The real-document diff is run separately and is the actual
acceptance-bar evidence.
"""
from __future__ import annotations

import pytest

from v1.analysis.snapshot_context import (
    DEFAULT_TAX_COMPLIANCE_CONFIG,
    _build_tax_compliance,
    _build_transaction_patterns,
)
from v1.analysis.snapshot_html_renderer import (
    _tax_compliance_ctx_from,
    _transaction_patterns_ctx_from,
)

_TAX_ROLES = ("tax_payment", "kra_payment")
_MIN_TAX_SAMPLE_SIZE = 3
_SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-2 source
# (backend/v1/analysis/snapshot_html_renderer.py as merged in PR #161).
# ─────────────────────────────────────────────────────────────────────────────

def _original_transaction_patterns_ctx(canon_raw_transactions):
    all_anomalies = []
    for t in canon_raw_transactions:
        for a in (t.get("anomalies") or []):
            all_anomalies.append({
                "type":     a.get("type") or "UNKNOWN",
                "severity": a.get("severity") or "LOW",
                "reason":   a.get("reason") or "",
                "abs_amount_cents": abs(int(t.get("signed_amount_cents") or 0)),
                "txn_date": t.get("txn_date") or "",
            })

    total_flagged  = len(all_anomalies)
    critical_count = sum(1 for a in all_anomalies if a["severity"] == "CRITICAL")
    high_count     = sum(1 for a in all_anomalies if a["severity"] == "HIGH")

    if all_anomalies:
        top_anomaly = max(
            all_anomalies,
            key=lambda a: (_SEVERITY_RANK.get(a["severity"], 0), a["abs_amount_cents"]),
        )
    else:
        top_anomaly = None

    if top_anomaly and top_anomaly["severity"] in ("CRITICAL", "HIGH"):
        top_pattern_clause = (
            f"The most significant: a {top_anomaly['type']} of "
            f"{_fmt_kes(top_anomaly['abs_amount_cents'])} on {top_anomaly['txn_date']} "
            f"({top_anomaly['reason']})."
        )
    else:
        top_pattern_clause = "No high-severity transaction patterns were detected."

    return {
        "critical_count":  critical_count,
        "high_count":      high_count,
        "total_flagged":   total_flagged,
        "total_txn_count": len(canon_raw_transactions),
        "clause":          top_pattern_clause,
    }


def _original_tax_compliance_ctx(txns, in_active_period):
    tax_months_active: set = set()
    tax_total_cents_active = 0
    tax_txn_count_active = 0
    all_months_active: set = set()
    for t in txns:
        m = (t["txn_date"] or "")[:7]
        if t["txn_date"] and in_active_period(m):
            all_months_active.add(m)
            if t["role"] in _TAX_ROLES and t["signed"] < 0:
                tax_months_active.add(m)
                tax_total_cents_active += t["abs"]
                tax_txn_count_active += 1

    n_tax_months   = len(tax_months_active)
    n_total_months = len(all_months_active)

    if n_total_months == 0 or tax_txn_count_active == 0:
        kra_compliance = "NOT_DETECTED"
    elif tax_txn_count_active < _MIN_TAX_SAMPLE_SIZE:
        kra_compliance = "INSUFFICIENT_DATA"
    elif n_tax_months >= n_total_months * 0.8:
        kra_compliance = "COMPLIANT"
    elif n_tax_months > 0:
        kra_compliance = "PARTIAL"
    else:
        kra_compliance = "NOT_DETECTED"

    if kra_compliance == "COMPLIANT":
        tax_compliance_clause = "Tax payment pattern is consistent with the business's stated activity level."
    elif kra_compliance == "PARTIAL":
        tax_compliance_clause = "Partial tax payment pattern — verify against filed returns."
    elif kra_compliance == "INSUFFICIENT_DATA":
        tax_compliance_clause = (
            f"Insufficient tax transaction volume for a reliable compliance "
            f"assessment (N={tax_txn_count_active})."
        )
    else:
        tax_compliance_clause = (
            "No tax payments detected in bank activity. This does not necessarily "
            "indicate non-compliance — tax may be paid from an account outside this "
            "statement set, or by a third party. Verify against a KRA compliance certificate."
        )

    return {
        "total_str":      _fmt_kes(tax_total_cents_active),
        "n_tax_months":   n_tax_months,
        "n_total_months": n_total_months,
        "kra_compliance": kra_compliance,
        "clause":         tax_compliance_clause,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _anomaly_txn(severity, amount_cents, txn_date="2026-03-01", type_="ROUND_NUMBER", reason="observed pattern"):
    return {
        "signed_amount_cents": -amount_cents,
        "txn_date": txn_date,
        "anomalies": [{"type": type_, "severity": severity, "reason": reason}],
    }


TRANSACTION_PATTERN_SCENARIOS = [
    pytest.param([], id="no_transactions"),
    pytest.param([{"signed_amount_cents": -100, "txn_date": "2026-01-01"}], id="txns_no_anomalies_key"),
    pytest.param([{"signed_amount_cents": -100, "txn_date": "2026-01-01", "anomalies": []}], id="empty_anomalies_list"),
    pytest.param([_anomaly_txn("LOW", 5000), _anomaly_txn("MEDIUM", 8000)], id="only_low_medium_no_high_severity_note"),
    pytest.param([_anomaly_txn("HIGH", 120000, txn_date="2026-02-14", type_="LARGE_ROUND", reason="near threshold")], id="single_high"),
    pytest.param([_anomaly_txn("CRITICAL", 900000, txn_date="2026-05-01", type_="STRUCTURING", reason="split deposits")], id="single_critical"),
    pytest.param(
        [_anomaly_txn("HIGH", 50000), _anomaly_txn("CRITICAL", 30000), _anomaly_txn("CRITICAL", 900000, txn_date="2026-06-01", type_="X", reason="biggest")],
        id="critical_beats_high_and_ties_broken_by_amount",
    ),
    pytest.param(
        [_anomaly_txn("LOW", 100), _anomaly_txn("HIGH", 500), _anomaly_txn("LOW", 999999)],
        id="amount_does_not_override_severity_rank",
    ),
]


@pytest.mark.parametrize("canon_raw_transactions", TRANSACTION_PATTERN_SCENARIOS)
def test_transaction_patterns_matches_original(canon_raw_transactions):
    old = _original_transaction_patterns_ctx(canon_raw_transactions)
    new_typed = _build_transaction_patterns(canon_raw_transactions)
    new = _transaction_patterns_ctx_from(new_typed)
    assert new == old, f"Transaction Pattern Analysis diverged.\nOLD: {old}\nNEW: {new}"


def _tax_txn(role, signed, txn_date):
    return {"role": role, "signed": signed, "abs": abs(signed), "txn_date": txn_date}


_ALWAYS_ACTIVE = lambda m: True  # noqa: E731
_FY2026_ONLY = lambda m: m.startswith("2026-")  # noqa: E731

TAX_COMPLIANCE_SCENARIOS = [
    pytest.param([], _ALWAYS_ACTIVE, id="no_txns"),
    pytest.param(
        [_tax_txn("revenue_operational", 10000, "2026-01-05")] * 3,
        _ALWAYS_ACTIVE, id="txns_present_zero_tax_not_detected",
    ),
    pytest.param(
        [_tax_txn("tax_payment", -5000, "2026-01-05"), _tax_txn("revenue_operational", 10000, "2026-02-01")],
        _ALWAYS_ACTIVE, id="one_tax_txn_insufficient_sample",
    ),
    pytest.param(
        [_tax_txn("tax_payment", -5000, m) for m in ("2026-01-05", "2026-02-05", "2026-03-05")]
        + [_tax_txn("revenue_operational", 10000, m) for m in ("2026-01-01", "2026-02-01", "2026-03-01")],
        _ALWAYS_ACTIVE, id="compliant_tax_every_active_month",
    ),
    pytest.param(
        [_tax_txn("tax_payment", -5000, m) for m in ("2026-01-05", "2026-02-05", "2026-03-05")]
        + [_tax_txn("revenue_operational", 10000, m) for m in ("2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01")],
        _ALWAYS_ACTIVE, id="partial_tax_coverage_below_80pct",
    ),
    pytest.param(
        [_tax_txn("kra_payment", -2000, "2026-01-05"), _tax_txn("kra_payment", -2000, "2026-02-05"), _tax_txn("kra_payment", -2000, "2026-03-05")]
        + [_tax_txn("revenue_operational", 10000, "2026-01-01")],
        _ALWAYS_ACTIVE, id="kra_payment_role_also_counts",
    ),
    pytest.param(
        [_tax_txn("tax_payment", -5000, "2025-12-05")]  # outside active period
        + [_tax_txn("revenue_operational", 10000, "2026-01-01"), _tax_txn("revenue_operational", 10000, "2026-02-01")],
        _FY2026_ONLY, id="active_period_filter_excludes_prior_year_tax",
    ),
    pytest.param(
        [_tax_txn("tax_payment", -5000, "2026-01-05")] * 3
        + [_tax_txn("revenue_operational", 10000, "2026-01-01")],
        _FY2026_ONLY, id="active_period_filter_keeps_in_year_compliant",
    ),
]


@pytest.mark.parametrize("txns, in_active_period", TAX_COMPLIANCE_SCENARIOS)
def test_tax_compliance_matches_original(txns, in_active_period):
    old = _original_tax_compliance_ctx(txns, in_active_period)
    new_typed = _build_tax_compliance(txns, in_active_period, DEFAULT_TAX_COMPLIANCE_CONFIG)
    new = _tax_compliance_ctx_from(new_typed)
    assert new == old, f"Tax Compliance Analysis diverged.\nOLD: {old}\nNEW: {new}"


def test_risk_assessment_critical_count_now_sources_from_transaction_patterns():
    """
    Stage 2 removes Stage 1's duplicate anomaly-counting loop inside
    build_snapshot_context() — risk.anomaly_narrative must now be driven by
    the SAME TransactionPatterns.critical_count Transaction Pattern Analysis
    itself reports, not a second independent count.
    """
    from v1.analysis.snapshot_context import _build_risk_assessment, DEFAULT_SUPPLIER_CONCENTRATION_CONFIG

    canon_raw_transactions = [
        _anomaly_txn("CRITICAL", 100000, txn_date="2026-01-01"),
        _anomaly_txn("CRITICAL", 200000, txn_date="2026-01-02"),
    ]
    tp = _build_transaction_patterns(canon_raw_transactions)
    assert tp.critical_count == 2

    risk = _build_risk_assessment([], "OBSERVED", {}, tp.critical_count, DEFAULT_SUPPLIER_CONCENTRATION_CONFIG)
    assert "2 critical transaction-pattern flag(s)" in risk.anomaly_narrative
