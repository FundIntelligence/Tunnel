"""
Shared snapshot-context data layer (PAR-189).

STATUS: partial extraction — Stage 1 of the incremental build_snapshot_context()
migration described in PAR-189. Only two sections are covered so far: Risk
Assessment Summary and Supplier Payment Analysis (both already implicated in
real content-drop bugs — PAR-188 and same-night testing respectively). The
remaining ~55 context keys / ~17 sections are still computed inline in
snapshot_html_renderer.render_snapshot_html() and are NOT reachable from this
module yet. See docs/PAR-189-shared-context-schema.md for the full target
schema and section mapping, and the PAR-189 ticket comment (2026-08-20) for
the ratified schema decisions this module follows.

Format-agnostic per PAR-189: nothing returned from this module contains HTML,
CSS class names, hex colours, or markup. Each renderer (WeasyPrint today,
reportlab later) owns its own mapping from these typed values to
presentation — see _supplier_payments_ctx_from() / _risk_assessment_ctx_from()
in snapshot_html_renderer.py for WeasyPrint's adapter.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from ..core.snapshot_engine import decompress_canonical_json_if_needed
from .snapshot_generator import generate_reconciliation_section
from ._snapshot_fetch_helpers import _get_supabase, _paginate

Cents = int

REVENUE_ROLES = {"revenue_operational", "mpesa_inflow", "pesalink_inflow"}
_SUPPLIER_ROLES = ("supplier", "supplier_payment")

Tier = Literal["OBSERVED", "LOW_CONFIDENCE", "MEDIUM_CONFIDENCE", "HIGH_CONFIDENCE"]
Materiality = Literal["NEGLIGIBLE", "MINOR", "MATERIAL", "CRITICAL"]
RevenueConcentrationState = Literal["OK", "INSUFFICIENT_DATA", "UNAVAILABLE"]
SupplierConcentration = Literal["HIGH", "MODERATE", "DIVERSIFIED", "INSUFFICIENT_DATA"]


@dataclass(frozen=True)
class Money:
    cents: Cents
    currency: str = "KES"


@dataclass(frozen=True)
class Percent:
    # Raw fraction, 0-1 (0.045 == 4.5%) — ratified PAR-189 comment,
    # 2026-08-20T12:27, decision #3. This SUPERSEDES the already-multiplied
    # (4.5 == 4.5%) convention proposed in docs/PAR-189-shared-context-schema.md
    # §2; that doc predates the ratification and is stale on this one point.
    value: float


@dataclass(frozen=True)
class SupplierConcentrationConfig:
    """
    high_threshold/moderate_threshold mirror the >30%/>15% "HIGH concentration"
    convention PARITY_SCIENCE.md Part III defines for Customer Concentration,
    reused here for the supplier side BY ANALOGY, not independently codified.
    BORROWED THRESHOLD, PENDING FORMAL PARITY SCIENCE SIGN-OFF (PAR-189 ratified
    decision #4) — carried as a named config value, not silently validated or
    changed by this extraction.

    min_sample_size is shared, unchanged, with the revenue-concentration
    sample-size gate in RiskAssessment — the original code used the exact same
    30-transaction constant (_MIN_SUPPLIER_SAMPLE_SIZE) for both. That
    coupling is preserved here rather than silently split into two configs.
    """
    high_threshold: float = 0.30
    moderate_threshold: float = 0.15
    min_sample_size: int = 30


DEFAULT_SUPPLIER_CONCENTRATION_CONFIG = SupplierConcentrationConfig()


@dataclass(frozen=True)
class SupplierPayments:
    available: bool
    total: Optional[Money] = None
    txn_count: Optional[int] = None
    counterparty_count: Optional[int] = None
    top_counterparty: Optional[str] = None
    top_share: Optional[Percent] = None
    concentration: Optional[SupplierConcentration] = None
    narrative: Optional[str] = None


@dataclass(frozen=True)
class RiskAssessment:
    tier: Tier
    advisory_tier: Optional[Materiality]
    coverage: Optional[Percent]
    largest_revenue_share: Optional[Percent]             # None unless state == OK
    revenue_concentration_sample: Optional[int]           # N, only for INSUFFICIENT_DATA
    revenue_concentration_state: RevenueConcentrationState
    anomaly_narrative: str
    conclusion: str            # PAR-188 disclosure #1 — required, never omitted
    transfer_caveat: str       # PAR-188 disclosure #2 — required, never omitted


def _fetch_txns_for_context(sb, deal_id: str) -> List[Dict]:
    """
    Minimal txn fetch for the two sections covered so far: role, signed
    amount, abs amount, entity_id. Mirrors render_snapshot_html()'s txns
    list construction exactly (same null-safe abs derivation) but skips
    balance/descriptor/date columns, which these two sections never read.
    """
    txn_rows = _paginate(
        sb, "pds_raw_transactions",
        "id, signed_amount_cents, abs_amount_cents",
        deal_id,
    )
    map_rows = _paginate(sb, "pds_txn_entity_map", "txn_id, role, entity_id", deal_id)
    role_by_txn = {r["txn_id"]: r["role"] for r in map_rows}
    entity_id_by_txn = {r["txn_id"]: r.get("entity_id") for r in map_rows}

    return [{
        "signed": t["signed_amount_cents"] or 0,
        "abs": t["abs_amount_cents"] if t["abs_amount_cents"] is not None else abs(t["signed_amount_cents"] or 0),
        "role": role_by_txn.get(t["id"], "other"),
        "entity_id": entity_id_by_txn.get(t["id"]),
    } for t in txn_rows]


def _build_supplier_payments(
    txns: List[Dict],
    entity_name_by_id: Dict[str, str],
    config: SupplierConcentrationConfig,
) -> SupplierPayments:
    supplier_by_entity: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "count": 0})
    for t in txns:
        if t["role"] in _SUPPLIER_ROLES and t["signed"] < 0:
            eid = t.get("entity_id") or ""
            supplier_by_entity[eid]["total"] += t["abs"]
            supplier_by_entity[eid]["count"] += 1

    supplier_total_cents = sum(v["total"] for v in supplier_by_entity.values())
    supplier_txn_count = sum(v["count"] for v in supplier_by_entity.values())
    supplier_entity_count = len(supplier_by_entity)

    if not supplier_by_entity or supplier_total_cents <= 0:
        return SupplierPayments(available=False)

    top_eid, top_data = max(supplier_by_entity.items(), key=lambda kv: kv[1]["total"])
    top_supplier_name = (
        entity_name_by_id.get(top_eid)
        or (top_eid[:16] + "…" if len(top_eid) > 16 else top_eid)
        or "--"
    )
    top_supplier_share = top_data["total"] / supplier_total_cents

    if supplier_txn_count < config.min_sample_size:
        concentration: SupplierConcentration = "INSUFFICIENT_DATA"
        narrative = (
            f"Insufficient supplier transaction volume for a reliable "
            f"concentration assessment (N={supplier_txn_count})."
        )
    elif top_supplier_share >= config.high_threshold:
        concentration = "HIGH"
        narrative = "This represents HIGH supplier concentration risk."
    elif top_supplier_share >= config.moderate_threshold:
        concentration = "MODERATE"
        narrative = "This represents MODERATE supplier concentration."
    else:
        concentration = "DIVERSIFIED"
        narrative = "Supplier spend is well-diversified across counterparties."

    return SupplierPayments(
        available=True,
        total=Money(cents=supplier_total_cents),
        txn_count=supplier_txn_count,
        counterparty_count=supplier_entity_count,
        top_counterparty=top_supplier_name,
        top_share=Percent(value=top_supplier_share),
        concentration=concentration,
        narrative=narrative,
    )


def _build_risk_assessment(
    txns: List[Dict],
    recon_tier: Tier,
    acct_cov_raw: Dict,
    critical_pattern_count: int,
    config: SupplierConcentrationConfig,
) -> RiskAssessment:
    coverage_pct_raw = acct_cov_raw.get("coverage_pct")
    account_coverage_available = coverage_pct_raw is not None
    advisory_tier_raw = acct_cov_raw.get("advisory_tier") if account_coverage_available else None
    advisory_tier: Optional[Materiality] = advisory_tier_raw if advisory_tier_raw else None
    coverage: Optional[Percent] = (
        Percent(value=coverage_pct_raw / 100) if account_coverage_available else None
    )

    revenue_by_entity: Dict[str, int] = defaultdict(int)
    revenue_txn_count = 0
    for t in txns:
        if t["role"] in REVENUE_ROLES and t["signed"] > 0:
            eid = t.get("entity_id") or ""
            revenue_by_entity[eid] += t["signed"]
            revenue_txn_count += 1
    revenue_total_cents = sum(revenue_by_entity.values())

    if not revenue_by_entity or revenue_total_cents <= 0:
        revenue_state: RevenueConcentrationState = "UNAVAILABLE"
        largest_revenue_share = None
        revenue_sample = None
    elif revenue_txn_count < config.min_sample_size:
        revenue_state = "INSUFFICIENT_DATA"
        largest_revenue_share = None
        revenue_sample = revenue_txn_count
    else:
        _, top_rev_total = max(revenue_by_entity.items(), key=lambda kv: kv[1])
        revenue_state = "OK"
        largest_revenue_share = Percent(value=top_rev_total / revenue_total_cents)
        revenue_sample = None

    if critical_pattern_count > 0:
        anomaly_narrative = (
            f"{critical_pattern_count} critical transaction-pattern flag(s) were also raised "
            "(see Transaction Pattern Analysis)."
        )
    else:
        anomaly_narrative = "No critical transaction-pattern flags were raised."

    if recon_tier == "OBSERVED":
        conclusion = (
            "This report covers bank-observed data only — audited financials have not been "
            "submitted, so the 4-point reconciliation has not run. Confidence reflects income "
            "quality and cashflow composition indicators only, not a reconciled tier."
        )
    elif recon_tier == "HIGH_CONFIDENCE":
        conclusion = "This deal meets Parity's threshold for high-confidence credit analysis."
    elif recon_tier == "MEDIUM_CONFIDENCE" and advisory_tier == "CRITICAL":
        conclusion = (
            "Confidence is capped at Medium because of a critical account-coverage gap — "
            "resolve missing bank statement coverage before treating this as high-confidence."
        )
    elif recon_tier == "MEDIUM_CONFIDENCE":
        conclusion = (
            "This deal is Medium confidence — cash position or loan activity reconciliation "
            "did not reach exact-match tolerance."
        )
    else:
        conclusion = (
            "This deal is Low confidence — cash position and/or loan activity reconciliation "
            "shows material variance. Manual review is required before credit decisioning."
        )

    transfer_caveat = (
        "This confidence tier does not yet net out self-transfers between this company's own "
        "bank accounts — see Inter-Account Transfer Analysis above for why that detection "
        "is not currently available."
    )

    return RiskAssessment(
        tier=recon_tier,
        advisory_tier=advisory_tier,
        coverage=coverage,
        largest_revenue_share=largest_revenue_share,
        revenue_concentration_sample=revenue_sample,
        revenue_concentration_state=revenue_state,
        anomaly_narrative=anomaly_narrative,
        conclusion=conclusion,
        transfer_caveat=transfer_caveat,
    )


def build_snapshot_context(
    deal_id: str,
    config: SupplierConcentrationConfig = DEFAULT_SUPPLIER_CONCENTRATION_CONFIG,
) -> Dict[str, object]:
    """
    PARTIAL — Stage 1 of PAR-189. Returns only:
        {"risk": RiskAssessment, "supplier_payments": SupplierPayments}
    NOT the full 57-key SnapshotContext from docs/PAR-189-shared-context-schema.md.
    Everything else render_snapshot_html() needs is still computed inline there.

    This function does its own independent deal/txn/recon fetch rather than
    being fed data already fetched by render_snapshot_html() — see the
    PAR-189 report for why that duplication exists at this stage and what it
    means for the remaining ~17 sections.
    """
    sb = _get_supabase()

    af_result = (
        sb.table("pds_audited_financials")
        .select("financial_year")
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    recon_available = len(af_result) > 0

    snap_res = (
        sb.table("pds_snapshots")
        .select("canonical_json")
        .eq("deal_id", deal_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    snap: Dict = snap_res.data[0] if snap_res.data else {}
    raw_cj = snap.get("canonical_json") or ""
    canonical_str = decompress_canonical_json_if_needed(raw_cj)
    canonical: Dict = json.loads(canonical_str) if canonical_str else {}

    recon_section: Dict = {}
    if recon_available:
        sealed_recon = canonical.get("recon_section")
        recon_section = sealed_recon if sealed_recon else generate_reconciliation_section(deal_id)
    acct_cov_raw: Dict = (recon_section.get("account_coverage") or {}) if recon_available else {}

    recon_tier: Tier = (recon_section.get("tier") or "LOW_CONFIDENCE") if recon_available else "OBSERVED"

    critical_pattern_count = sum(
        1
        for t in (canonical.get("transactions") or [])
        for a in (t.get("anomalies") or [])
        if (a.get("severity") or "LOW") == "CRITICAL"
    )

    txns = _fetch_txns_for_context(sb, deal_id)

    entity_rows = _paginate(sb, "pds_entities", "entity_id, display_name", deal_id)
    entity_name_by_id: Dict[str, str] = {
        e["entity_id"]: e.get("display_name") for e in entity_rows
    }

    supplier_payments = _build_supplier_payments(txns, entity_name_by_id, config)
    risk = _build_risk_assessment(txns, recon_tier, acct_cov_raw, critical_pattern_count, config)

    return {"risk": risk, "supplier_payments": supplier_payments}
