"""
Shared snapshot-context data layer (PAR-189).

STATUS: partial extraction. Stage 1 covered Risk Assessment Summary and
Supplier Payment Analysis (both already implicated in real content-drop bugs
— PAR-188 and same-night testing respectively). Stage 2 adds Transaction
Pattern Analysis and Tax Compliance Analysis. The remaining ~13 sections are
still computed inline in snapshot_html_renderer.render_snapshot_html() and
are NOT reachable from this module yet. See docs/PAR-189-shared-context-schema.md
for the full target schema and section mapping, and the PAR-189 ticket
comments (2026-08-20) for the ratified schema decisions this module follows.

Stage 2 note: Risk Assessment Summary's anomaly count (risk.anomaly_narrative)
now sources from TransactionPatterns.critical_count instead of a second,
separately-computed anomaly loop — Stage 1 duplicated that computation because
Transaction Pattern Analysis wasn't extracted yet; Stage 2 removes the
duplication now that it is.

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
_TAX_ROLES = ("tax_payment", "kra_payment")
_SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}

Tier = Literal["OBSERVED", "LOW_CONFIDENCE", "MEDIUM_CONFIDENCE", "HIGH_CONFIDENCE"]
Materiality = Literal["NEGLIGIBLE", "MINOR", "MATERIAL", "CRITICAL"]
RevenueConcentrationState = Literal["OK", "INSUFFICIENT_DATA", "UNAVAILABLE"]
SupplierConcentration = Literal["HIGH", "MODERATE", "DIVERSIFIED", "INSUFFICIENT_DATA"]
KraStatus = Literal["COMPLIANT", "PARTIAL", "INSUFFICIENT_DATA", "NOT_DETECTED"]


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


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
class TaxComplianceConfig:
    """
    Both values were hardcoded in the original inline logic and are pulled
    into named config per PAR-189 ratified decision #4 ("any threshold values
    currently hardcoded in logic get pulled into named config fields ...
    carry the value, don't silently validate or change it"). Unlike the
    supplier concentration threshold, neither of these is flagged in the
    original code as borrowed/unratified — the code comment gives an explicit
    reasoned justification for 3 (a quarter's worth of monthly-cadence tax
    activity) — so no PENDING SIGN-OFF caveat applies here, only the general
    "carry as config, don't hardcode" rule.
    """
    min_sample_size: int = 3
    compliant_coverage_threshold: float = 0.8  # months_with_tax / months_total >= this -> COMPLIANT


DEFAULT_TAX_COMPLIANCE_CONFIG = TaxComplianceConfig()


@dataclass(frozen=True)
class TaxCompliance:
    total: Money
    months_with_tax: int
    months_total: int
    status: KraStatus
    narrative: str


@dataclass(frozen=True)
class TransactionPatterns:
    critical_count: int
    high_count: int
    total_flagged: int
    total_txn_count: int
    narrative: str


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
    Minimal txn fetch for the sections covered so far: txn_date, role,
    signed amount, abs amount, entity_id. Mirrors render_snapshot_html()'s
    txns list construction exactly (same null-safe abs derivation) but skips
    balance/descriptor/account/document columns, which none of these
    sections read.
    """
    txn_rows = _paginate(
        sb, "pds_raw_transactions",
        "id, txn_date, signed_amount_cents, abs_amount_cents",
        deal_id,
    )
    map_rows = _paginate(sb, "pds_txn_entity_map", "txn_id, role, entity_id", deal_id)
    role_by_txn = {r["txn_id"]: r["role"] for r in map_rows}
    entity_id_by_txn = {r["txn_id"]: r.get("entity_id") for r in map_rows}

    return [{
        "txn_date": t["txn_date"],
        "signed": t["signed_amount_cents"] or 0,
        "abs": t["abs_amount_cents"] if t["abs_amount_cents"] is not None else abs(t["signed_amount_cents"] or 0),
        "role": role_by_txn.get(t["id"], "other"),
        "entity_id": entity_id_by_txn.get(t["id"]),
    } for t in txn_rows]


def _build_transaction_patterns(canon_raw_transactions: List[Dict]) -> TransactionPatterns:
    all_anomalies: List[Dict] = []
    for t in canon_raw_transactions:
        for a in (t.get("anomalies") or []):
            all_anomalies.append({
                "type": a.get("type") or "UNKNOWN",
                "severity": a.get("severity") or "LOW",
                "reason": a.get("reason") or "",
                "abs_amount_cents": abs(int(t.get("signed_amount_cents") or 0)),
                "txn_date": t.get("txn_date") or "",
            })

    total_flagged = len(all_anomalies)
    critical_count = sum(1 for a in all_anomalies if a["severity"] == "CRITICAL")
    high_count = sum(1 for a in all_anomalies if a["severity"] == "HIGH")

    top_anomaly = (
        max(all_anomalies, key=lambda a: (_SEVERITY_RANK.get(a["severity"], 0), a["abs_amount_cents"]))
        if all_anomalies else None
    )

    if top_anomaly and top_anomaly["severity"] in ("CRITICAL", "HIGH"):
        narrative = (
            f"The most significant: a {top_anomaly['type']} of "
            f"{_fmt_kes(top_anomaly['abs_amount_cents'])} on {top_anomaly['txn_date']} "
            f"({top_anomaly['reason']})."
        )
    else:
        narrative = "No high-severity transaction patterns were detected."

    return TransactionPatterns(
        critical_count=critical_count,
        high_count=high_count,
        total_flagged=total_flagged,
        total_txn_count=len(canon_raw_transactions),
        narrative=narrative,
    )


def _build_tax_compliance(
    txns: List[Dict],
    in_active_period,
    config: TaxComplianceConfig,
) -> TaxCompliance:
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

    n_tax_months = len(tax_months_active)
    n_total_months = len(all_months_active)

    if n_total_months == 0 or tax_txn_count_active == 0:
        status: KraStatus = "NOT_DETECTED"
    elif tax_txn_count_active < config.min_sample_size:
        status = "INSUFFICIENT_DATA"
    elif n_tax_months >= n_total_months * config.compliant_coverage_threshold:
        status = "COMPLIANT"
    elif n_tax_months > 0:
        status = "PARTIAL"
    else:
        status = "NOT_DETECTED"

    if status == "COMPLIANT":
        narrative = "Tax payment pattern is consistent with the business's stated activity level."
    elif status == "PARTIAL":
        narrative = "Partial tax payment pattern — verify against filed returns."
    elif status == "INSUFFICIENT_DATA":
        narrative = (
            f"Insufficient tax transaction volume for a reliable compliance "
            f"assessment (N={tax_txn_count_active})."
        )
    else:
        narrative = (
            "No tax payments detected in bank activity. This does not necessarily "
            "indicate non-compliance — tax may be paid from an account outside this "
            "statement set, or by a third party. Verify against a KRA compliance certificate."
        )

    return TaxCompliance(
        total=Money(cents=tax_total_cents_active),
        months_with_tax=n_tax_months,
        months_total=n_total_months,
        status=status,
        narrative=narrative,
    )


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
    supplier_config: SupplierConcentrationConfig = DEFAULT_SUPPLIER_CONCENTRATION_CONFIG,
    tax_config: TaxComplianceConfig = DEFAULT_TAX_COMPLIANCE_CONFIG,
) -> Dict[str, object]:
    """
    PARTIAL — Stage 2 of PAR-189. Returns:
        {"risk": RiskAssessment, "supplier_payments": SupplierPayments,
         "transaction_patterns": TransactionPatterns, "tax_compliance": TaxCompliance}
    NOT the full 57-key SnapshotContext from docs/PAR-189-shared-context-schema.md.
    Everything else render_snapshot_html() needs is still computed inline there —
    including a small residual fragment of what used to be the Tax Compliance
    Analysis loop (payroll_stability_live / n_payroll_months / n_total_months),
    kept inline because the not-yet-extracted Observed Patterns section reads
    those same local variables. See the PAR-189 Stage 2 report for detail.

    This function does its own independent deal/txn/recon fetch rather than
    being fed data already fetched by render_snapshot_html() — see the
    PAR-189 report for why that duplication exists at this stage and what it
    means for the remaining sections.
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
    af_financial_year = af_result[0].get("financial_year") if recon_available else None

    if recon_available and af_financial_year:
        _active_year = str(af_financial_year)
        in_active_period = lambda m: m.startswith(f"{_active_year}-")  # noqa: E731
    else:
        in_active_period = lambda m: True  # noqa: E731

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

    transaction_patterns = _build_transaction_patterns(canonical.get("transactions") or [])

    txns = _fetch_txns_for_context(sb, deal_id)

    entity_rows = _paginate(sb, "pds_entities", "entity_id, display_name", deal_id)
    entity_name_by_id: Dict[str, str] = {
        e["entity_id"]: e.get("display_name") for e in entity_rows
    }

    supplier_payments = _build_supplier_payments(txns, entity_name_by_id, supplier_config)
    tax_compliance = _build_tax_compliance(txns, in_active_period, tax_config)
    risk = _build_risk_assessment(
        txns, recon_tier, acct_cov_raw, transaction_patterns.critical_count, supplier_config,
    )

    return {
        "risk": risk,
        "supplier_payments": supplier_payments,
        "transaction_patterns": transaction_patterns,
        "tax_compliance": tax_compliance,
    }
