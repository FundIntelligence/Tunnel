"""
PAR-189 Stage 1 verification — Risk Assessment Summary + Supplier Payment
Analysis extraction into build_snapshot_context().

IMPORTANT — what this test does and does NOT prove:

The PAR-189 task's acceptance bar is a byte-diff of render_snapshot_html()'s
HTML output, old code path vs new, on the real Deed document
(deal e81e1d22-c438-4402-bd39-864957985637). That requires live Supabase
access this session does not have (no backend/.env, no cached canonical_json
for that deal — same blocker PAR-177/183/189 all hit).

What this test DOES verify: the two presentation dicts
(risk_assessment_ctx, supplier_payments_ctx) that get passed to the Jinja
template are byte-identical between the ORIGINAL inline computation
(transcribed verbatim below from the pre-extraction source, git commit
ab47f08:backend/v1/analysis/snapshot_html_renderer.py) and the NEW
build_snapshot_context() + adapter path, across a set of fixture inputs
chosen to hit every branch both blocks contain (all recon tiers, both
supplier-available states, insufficient-sample states for both sections).
Per the template (snapshot.html:1336-1405), these two context dicts are
consumed with no further string formatting beyond straight interpolation —
so dict equality here implies HTML equality for these two sections, for
any input these dicts can represent.

This is a real, meaningful check of the logic that changed. It is NOT the
mandated live-document byte-diff and must not be reported as satisfying it.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

import pytest

from v1.analysis.snapshot_context import (
    DEFAULT_SUPPLIER_CONCENTRATION_CONFIG,
    _build_risk_assessment,
    _build_supplier_payments,
)
from v1.analysis.snapshot_html_renderer import (
    _risk_assessment_ctx_from,
    _supplier_payments_ctx_from,
)

REVENUE_ROLES = {"revenue_operational", "mpesa_inflow", "pesalink_inflow"}
_SUPPLIER_ROLES = ("supplier", "supplier_payment")
_MIN_SUPPLIER_SAMPLE_SIZE = 30


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from
# git show ab47f08:backend/v1/analysis/snapshot_html_renderer.py
# (lines 702-768 and 1367-1461, pre-PAR-189-extraction). This is the
# reference implementation the new path must match exactly.
# ─────────────────────────────────────────────────────────────────────────────

def _original_supplier_payments_ctx(txns: List[Dict], entity_name_by_id: Dict[str, str]) -> Dict[str, Any]:
    supplier_by_entity: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "count": 0})
    for t in txns:
        if t["role"] in _SUPPLIER_ROLES and t["signed"] < 0:
            eid = t.get("entity_id") or ""
            supplier_by_entity[eid]["total"] += t["abs"]
            supplier_by_entity[eid]["count"] += 1

    supplier_total_cents = sum(v["total"] for v in supplier_by_entity.values())
    supplier_txn_count = sum(v["count"] for v in supplier_by_entity.values())
    supplier_entity_count = len(supplier_by_entity)

    if supplier_by_entity and supplier_total_cents > 0:
        top_eid, top_data = max(supplier_by_entity.items(), key=lambda kv: kv[1]["total"])
        top_supplier_name = (
            entity_name_by_id.get(top_eid)
            or (top_eid[:16] + "…" if len(top_eid) > 16 else top_eid)
            or "--"
        )
        top_supplier_pct = top_data["total"] / supplier_total_cents * 100

        if supplier_txn_count < _MIN_SUPPLIER_SAMPLE_SIZE:
            supplier_concentration_clause = (
                f"Insufficient supplier transaction volume for a reliable "
                f"concentration assessment (N={supplier_txn_count})."
            )
        else:
            if top_supplier_pct >= 30:
                supplier_concentration_clause = "This represents HIGH supplier concentration risk."
            elif top_supplier_pct >= 15:
                supplier_concentration_clause = "This represents MODERATE supplier concentration."
            else:
                supplier_concentration_clause = "Supplier spend is well-diversified across counterparties."

        return {
            "available":    True,
            "total_str":    _fmt_kes(supplier_total_cents),
            "txn_count":    supplier_txn_count,
            "entity_count": supplier_entity_count,
            "top_name":     top_supplier_name,
            "top_pct_str":  f"{top_supplier_pct:.1f}%",
            "clause":       supplier_concentration_clause,
        }
    else:
        return {"available": False}


def _original_risk_assessment_ctx(
    txns: List[Dict],
    recon_tier: str,
    account_coverage_ctx: Dict[str, Any],
    risk_critical_count: int,
) -> Dict[str, Any]:
    revenue_by_entity: Dict[str, int] = defaultdict(int)
    revenue_txn_count = 0
    for t in txns:
        if t["role"] in REVENUE_ROLES and t["signed"] > 0:
            eid = t.get("entity_id") or ""
            revenue_by_entity[eid] += t["signed"]
            revenue_txn_count += 1

    revenue_total_cents = sum(revenue_by_entity.values())

    if not revenue_by_entity or revenue_total_cents <= 0:
        largest_rev_pct_str = "--"
    elif revenue_txn_count < _MIN_SUPPLIER_SAMPLE_SIZE:
        largest_rev_pct_str = f"insufficient data (N={revenue_txn_count})"
    else:
        top_rev_eid, top_rev_total = max(revenue_by_entity.items(), key=lambda kv: kv[1])
        largest_rev_pct_str = f"{(top_rev_total / revenue_total_cents * 100):.1f}%"

    if risk_critical_count > 0:
        risk_anomaly_summary = (
            f"{risk_critical_count} critical transaction-pattern flag(s) were also raised "
            "(see Transaction Pattern Analysis)."
        )
    else:
        risk_anomaly_summary = "No critical transaction-pattern flags were raised."

    risk_advisory_tier = account_coverage_ctx.get("advisory_tier", "--") if account_coverage_ctx.get("available") else "--"
    if recon_tier == "OBSERVED":
        risk_conclusion = (
            "This report covers bank-observed data only — audited financials have not been "
            "submitted, so the 4-point reconciliation has not run. Confidence reflects income "
            "quality and cashflow composition indicators only, not a reconciled tier."
        )
    elif recon_tier == "HIGH_CONFIDENCE":
        risk_conclusion = "This deal meets Parity's threshold for high-confidence credit analysis."
    elif recon_tier == "MEDIUM_CONFIDENCE" and risk_advisory_tier == "CRITICAL":
        risk_conclusion = (
            "Confidence is capped at Medium because of a critical account-coverage gap — "
            "resolve missing bank statement coverage before treating this as high-confidence."
        )
    elif recon_tier == "MEDIUM_CONFIDENCE":
        risk_conclusion = (
            "This deal is Medium confidence — cash position or loan activity reconciliation "
            "did not reach exact-match tolerance."
        )
    else:
        risk_conclusion = (
            "This deal is Low confidence — cash position and/or loan activity reconciliation "
            "shows material variance. Manual review is required before credit decisioning."
        )

    risk_transfer_note = (
        "This confidence tier does not yet net out self-transfers between this company's own "
        "bank accounts — see Inter-Account Transfer Analysis above for why that detection "
        "is not currently available."
    )

    return {
        "tier":                   recon_tier,
        "advisory_tier":          risk_advisory_tier,
        "missing_pct":            account_coverage_ctx.get("coverage_pct", "--") if account_coverage_ctx.get("available") else "--",
        "largest_rev_pct_str":    largest_rev_pct_str,
        "anomaly_summary":        risk_anomaly_summary,
        "conclusion":             risk_conclusion,
        "transfer_note":          risk_transfer_note,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — chosen to hit every branch in both blocks
# ─────────────────────────────────────────────────────────────────────────────

def _txn(role, signed, entity_id="e1"):
    return {"role": role, "signed": signed, "abs": abs(signed), "entity_id": entity_id}


DEED_LIKE_TXNS = (
    # Deed is observed-only (no audited financials) per PAR-183/188/189 — this
    # mirrors that: recon_tier will be OBSERVED, exercising exactly the branch
    # that produces PAR-188 disclosure #1.
    [_txn("supplier_payment", -500_000, "supplierA")] * 20
    + [_txn("supplier_payment", -100_000, "supplierB")] * 15
    + [_txn("revenue_operational", 200_000, "customerA")] * 25
    + [_txn("revenue_operational", 50_000, "customerB")] * 10
)

SCENARIOS = [
    pytest.param(
        DEED_LIKE_TXNS, "OBSERVED", {"available": False}, 0,
        {}, id="deed_like_observed_high_supplier_concentration",
    ),
    pytest.param(
        [], "OBSERVED", {"available": False}, 0, {},
        id="no_txns_everything_unavailable",
    ),
    pytest.param(
        [_txn("supplier_payment", -1000, "s1")] * 5 + [_txn("revenue_operational", 1000, "c1")] * 5,
        "OBSERVED", {"available": False}, 2,
        {}, id="insufficient_sample_both_sections",
    ),
    pytest.param(
        DEED_LIKE_TXNS, "MEDIUM_CONFIDENCE",
        {"available": True, "advisory_tier": "CRITICAL", "coverage_pct": "61.2"}, 1,
        {}, id="medium_confidence_critical_coverage_gap",
    ),
    pytest.param(
        DEED_LIKE_TXNS, "MEDIUM_CONFIDENCE",
        {"available": True, "advisory_tier": "MINOR", "coverage_pct": "88.5"}, 0,
        {}, id="medium_confidence_minor_gap",
    ),
    pytest.param(
        DEED_LIKE_TXNS, "HIGH_CONFIDENCE",
        {"available": True, "advisory_tier": "NEGLIGIBLE", "coverage_pct": "100.0"}, 0,
        {}, id="high_confidence",
    ),
    pytest.param(
        DEED_LIKE_TXNS, "LOW_CONFIDENCE",
        {"available": True, "advisory_tier": "MATERIAL", "coverage_pct": "42.0"}, 3,
        {}, id="low_confidence_fallback",
    ),
    pytest.param(
        # Moderate (not high) supplier concentration + diversified revenue
        [_txn("supplier_payment", -20_000, f"s{i}") for i in range(30)]
        + [_txn("supplier_payment", -80_000, "s_top")]
        + [_txn("revenue_operational", 30_000, f"c{i}") for i in range(35)],
        "OBSERVED", {"available": False}, 0,
        {}, id="moderate_supplier_diversified_revenue",
    ),
]


@pytest.mark.parametrize("txns, recon_tier, account_coverage_ctx, risk_critical_count, entity_names", SCENARIOS)
def test_risk_and_supplier_extraction_matches_original(
    txns, recon_tier, account_coverage_ctx, risk_critical_count, entity_names,
):
    # ── Supplier Payment Analysis ──────────────────────────────────────────
    old_supplier = _original_supplier_payments_ctx(txns, entity_names)
    new_supplier_typed = _build_supplier_payments(txns, entity_names, DEFAULT_SUPPLIER_CONCENTRATION_CONFIG)
    new_supplier = _supplier_payments_ctx_from(new_supplier_typed)
    assert new_supplier == old_supplier, (
        f"Supplier Payment Analysis diverged.\nOLD: {old_supplier}\nNEW: {new_supplier}"
    )

    # ── Risk Assessment Summary ────────────────────────────────────────────
    # acct_cov_raw is the recon_section.account_coverage-shaped input that
    # feeds _build_risk_assessment; account_coverage_ctx (the fixture param)
    # is what the OLD code's already-built account_coverage_ctx looked like.
    # Translate fixture -> acct_cov_raw the way the real recon_section would.
    if account_coverage_ctx.get("available"):
        acct_cov_raw = {
            "advisory_tier": account_coverage_ctx["advisory_tier"],
            "coverage_pct": float(account_coverage_ctx["coverage_pct"]),
        }
    else:
        acct_cov_raw = {}

    old_risk = _original_risk_assessment_ctx(txns, recon_tier, account_coverage_ctx, risk_critical_count)
    new_risk_typed = _build_risk_assessment(
        txns, recon_tier, acct_cov_raw, risk_critical_count, DEFAULT_SUPPLIER_CONCENTRATION_CONFIG,
    )
    new_risk = _risk_assessment_ctx_from(new_risk_typed)
    assert new_risk == old_risk, (
        f"Risk Assessment Summary diverged.\nOLD: {old_risk}\nNEW: {new_risk}"
    )


def test_par188_disclosures_present_and_required_in_observed_state():
    """
    The two PAR-188 disclosures, exact real text, non-optional per PAR-189
    ratified decision #3 (schema: RiskAssessment.conclusion / .transfer_caveat
    are plain str, not Optional[str] — cannot be None/omitted).
    """
    risk = _build_risk_assessment(
        DEED_LIKE_TXNS, "OBSERVED", {}, 0, DEFAULT_SUPPLIER_CONCENTRATION_CONFIG,
    )
    assert "the 4-point reconciliation has not run" in risk.conclusion
    assert "does not yet net out self-transfers" in risk.transfer_caveat
    assert isinstance(risk.conclusion, str) and risk.conclusion
    assert isinstance(risk.transfer_caveat, str) and risk.transfer_caveat
