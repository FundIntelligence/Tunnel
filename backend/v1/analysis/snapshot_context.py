"""
Shared snapshot-context data layer (PAR-189).

STATUS: partial extraction. Stage 1 covered Risk Assessment Summary and
Supplier Payment Analysis (both already implicated in real content-drop bugs
— PAR-188 and same-night testing respectively). Stage 2 added Transaction
Pattern Analysis and Tax Compliance Analysis. Stage 3 added Analyst Notes and
Inventory Analysis. Stage 4 added Loan Activity Detected and Loan Facilities
(one LoanActivity concept spanning two template sections). Stage 5 added
Inflow Composition and Outflow Composition. Stage 6 adds Tax Payment Pattern.
The remaining ~8 sections are still computed inline in
snapshot_html_renderer.render_snapshot_html() and are NOT reachable from this
module yet. See docs/PAR-189-shared-context-schema.md for the full target
schema and section mapping, and the PAR-189 ticket comments (2026-08-20) for
the ratified schema decisions this module follows.

Stage 6 note: Tax Payment Pattern is a DIFFERENT role filter from Tax
Compliance Analysis (Stage 2) despite the similar name and shared "tax"
domain — see TaxPaymentPattern's docstring for the exact discrepancy
(role == "tax_payment" only, vs. TaxCompliance's _TAX_ROLES matching both
"tax_payment" and "kra_payment"). Confirmed by direct read of the original
inline code, not assumed from naming similarity, and preserved exactly
rather than unified.

Stage 2 note: Risk Assessment Summary's anomaly count (risk.anomaly_narrative)
now sources from TransactionPatterns.critical_count instead of a second,
separately-computed anomaly loop — Stage 1 duplicated that computation because
Transaction Pattern Analysis wasn't extracted yet; Stage 2 removes the
duplication now that it is.

Stage 3 note: Inventory's days_inventory_outstanding and turnover are kept as
raw, UNROUNDED floats (not the Optional[int]/pre-rounded form one might
expect) specifically so the WeasyPrint adapter's f"{value:.0f} days" /
f"{value:.1f}x" formatting reproduces the original single-step computation
exactly — rounding once in the data layer and again in the adapter risks a
rounding-order mismatch, the same reasoning already applied to Percent in
Stage 1. extraction_confidence is also kept a plain float, deliberately NOT
wrapped in Percent — the original template displays it as "0.87", never
"87%", so treating it as a Percent (which the WeasyPrint adapter would
multiply by 100) would silently produce the wrong number.

Stage 5 note: Segment.share (Inflow/Outflow Composition) is NOT each
segment's true fraction of the total. The original computes each segment's
displayed percentage as max(1, int(total/grand_total*100)) — an integer
floor with a minimum of 1% for any included segment — and the "Other"
bucket's percentage as 100 minus the SUM of the other segments' already-
floored percentages (a chart-must-sum-to-100 residual, not other/total on
its own). Both are display-layer artifacts of the original, not a
recomputable property of the segment's raw amount. Preserved exactly:
share.value stores that already-computed integer percentage divided by 100,
not amount/total. Recomputing a "true" share here would silently change
what every segment displays.

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
from typing import Dict, List, Literal, Optional, Tuple

from ..analytics import CASHFLOW_INFLOW_ROLES
from ..core.snapshot_engine import decompress_canonical_json_if_needed
from .snapshot_generator import generate_reconciliation_section
from ._snapshot_fetch_helpers import _get_supabase, _paginate

Cents = int

REVENUE_ROLES = {"revenue_operational", "mpesa_inflow", "pesalink_inflow"}
_SUPPLIER_ROLES = ("supplier", "supplier_payment")
_TAX_ROLES = ("tax_payment", "kra_payment")
_TAX_PENALTY_KEYWORDS = ("PENALTY", "PENALT", "SURCHARGE", "FINE")
_SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}

Tier = Literal["OBSERVED", "LOW_CONFIDENCE", "MEDIUM_CONFIDENCE", "HIGH_CONFIDENCE"]
Materiality = Literal["NEGLIGIBLE", "MINOR", "MATERIAL", "CRITICAL"]
RevenueConcentrationState = Literal["OK", "INSUFFICIENT_DATA", "UNAVAILABLE"]
SupplierConcentration = Literal["HIGH", "MODERATE", "DIVERSIFIED", "INSUFFICIENT_DATA"]
KraStatus = Literal["COMPLIANT", "PARTIAL", "INSUFFICIENT_DATA", "NOT_DETECTED"]
ReconStatus = Literal["EXACT_MATCH", "ACCEPTABLE", "COVERAGE_GAP", "VARIANCE"]


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
class TaxPaymentPattern:
    """
    Deliberately a SEPARATE role filter from TaxCompliance above, not a
    reuse: the original inline computation (snapshot_html_renderer.py:565,
    pre-Stage-6) matches ONLY role == "tax_payment", never "kra_payment" —
    unlike TaxCompliance's _TAX_ROLES tuple, which matches both. Confirmed
    by direct read, not assumed from the similar name. Preserved exactly;
    NOT unified with _TAX_ROLES, since doing so would silently change which
    transactions this section counts whenever a "kra_payment"-role
    transaction exists.
    """
    txn_count: int
    avg_per_month: Optional[float]   # raw, unrounded — None only when zero tax-months exist (original's "--")
    penalty_count: int
    total: Money
    jan_spike: bool                  # drives narrative choice — true whenever ANY tax txn falls in a
                                      # January month, independent of that month's total (see jan_spike_total)
    jan_spike_total: Optional[Money] # None when the January total is <= 0 (original's own row-suppression
                                      # check is `jan_total > 0`, a different condition from jan_spike itself —
                                      # both preserved separately rather than collapsed into one)
    narrative: str


@dataclass(frozen=True)
class TransactionPatterns:
    critical_count: int
    high_count: int
    total_flagged: int
    total_txn_count: int
    narrative: str


@dataclass(frozen=True)
class InventoryConfig:
    """
    Both cutoffs were hardcoded in the original inline logic; pulled into
    named config per PAR-189 ratified decision #4. Neither is flagged in the
    original code as borrowed/unratified (no PARITY_SCIENCE.md cross-
    reference, unlike supplier concentration), so no pending-sign-off caveat
    applies — just the general carry-as-config rule.
    """
    low_risk_turnover_threshold: float = 6.0       # turnover >= this -> LOW risk
    moderate_turnover_threshold: float = 3.0        # turnover >= this -> moderate


DEFAULT_INVENTORY_CONFIG = InventoryConfig()


@dataclass(frozen=True)
class Inventory:
    available: bool
    fiscal_year: Optional[str] = None
    inventory: Optional[Money] = None
    cost_of_sales: Optional[Money] = None
    turnover: Optional[float] = None                       # raw, unrounded — see module docstring
    days_inventory_outstanding: Optional[float] = None      # raw, unrounded — see module docstring
    extraction_confidence: Optional[float] = None           # NOT a Percent — see module docstring
    narrative: Optional[str] = None


@dataclass(frozen=True)
class LoanFacility:
    name: str
    amount: Money
    status: ReconStatus   # resolved 4-way status; renderer's own table maps this to badge class/label


@dataclass(frozen=True)
class LoanActivity:
    disbursed: Money
    repaid: Money
    net: Money                              # signed; renderer takes abs() for display, same as original
    repayments_per_month: float
    repayment_txn_count: int
    facilities: List[LoanFacility]
    bank_net: Money                         # always present (defaults to 0), never truly "unavailable"
    declared_net: Money                     # always present (defaults to 0), never truly "unavailable"
    variance: Optional[Percent]             # None -> renderer shows "0%" (original's own quirk, preserved
                                             # exactly — NOT the usual "--" missing-data convention)
    status_raw: Optional[str]               # verbatim recon status text (e.g. "HEALTHY"), for direct
                                             # display — deliberately NOT collapsed into ReconStatus: the
                                             # template prints this string as-is (snapshot.html:1224), and
                                             # ReconStatus's 4 buckets would lose real values like "HEALTHY"
                                             # or "ACCEPTABLE_VARIANCE" that _status_to_badge() collapses
                                             # for badge purposes only. Kept separate deliberately — not in
                                             # docs/PAR-189-shared-context-schema.md's proposed LoanActivity,
                                             # added here because byte-fidelity requires it.


@dataclass(frozen=True)
class Segment:
    key: str            # stable id (e.g. "procurement_cogs") — renderer owns colour, per design doc §2
    label: str
    amount: Money
    share: Percent       # NOT the segment's true fraction of the total — see module docstring: this
                          # preserves the original's own display-layer floor-to-min-1%/residual-for-
                          # "other" logic exactly, re-expressed as a 0-1 fraction for schema compliance.


@dataclass(frozen=True)
class Composition:
    total: Money
    segments: List[Segment]
    advisory: Optional[str] = None   # None -> renderer shows "" (inflow_warn/outflow_warn's original default)


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
    signed amount, abs amount, descriptor, entity_id. Mirrors
    render_snapshot_html()'s txns list construction exactly (same
    null-safe abs derivation) but skips balance/account/document columns,
    which none of these sections read. Stage 6 added normalized_descriptor
    (-> "desc") for Tax Payment Pattern's penalty-keyword detection.
    """
    txn_rows = _paginate(
        sb, "pds_raw_transactions",
        "id, txn_date, signed_amount_cents, abs_amount_cents, normalized_descriptor",
        deal_id,
    )
    map_rows = _paginate(sb, "pds_txn_entity_map", "txn_id, role, entity_id", deal_id)
    role_by_txn = {r["txn_id"]: r["role"] for r in map_rows}
    entity_id_by_txn = {r["txn_id"]: r.get("entity_id") for r in map_rows}

    return [{
        "txn_date": t["txn_date"],
        "signed": t["signed_amount_cents"] or 0,
        "abs": t["abs_amount_cents"] if t["abs_amount_cents"] is not None else abs(t["signed_amount_cents"] or 0),
        "desc": t["normalized_descriptor"] or "",
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


def _build_inventory(
    af: Dict,
    recon_available: bool,
    config: InventoryConfig,
) -> Inventory:
    fiscal_year = str(af.get("financial_year") or "") if recon_available else ""
    inventory_cents_raw = af.get("inventory_cents") if recon_available else None
    cost_of_sales_cents_raw = af.get("cost_of_sales_cents") if recon_available else None
    extraction_confidence_raw = af.get("extraction_confidence") if recon_available else None

    data_present = (
        recon_available
        and inventory_cents_raw is not None
        and cost_of_sales_cents_raw is not None
        and int(inventory_cents_raw) > 0
    )

    if not data_present:
        narrative = (
            f"Inventory and/or cost of sales figures were not present in the audited "
            f"financial statements provided for FY{fiscal_year} — inventory analysis cannot "
            "be computed for this deal."
        ) if recon_available else (
            "Inventory analysis requires audited financials — not yet submitted for this deal."
        )
        return Inventory(available=False, fiscal_year=fiscal_year or None, narrative=narrative)

    inventory_cents = int(inventory_cents_raw)
    cost_of_sales_cents = int(cost_of_sales_cents_raw)
    turnover = cost_of_sales_cents / inventory_cents
    dio = 365 / turnover if turnover > 0 else None

    if turnover >= config.low_risk_turnover_threshold:
        narrative = "Inventory turns over quickly relative to cost of sales — LOW inventory risk."
    elif turnover >= config.moderate_turnover_threshold:
        narrative = "Inventory turnover is moderate."
    else:
        narrative = (
            "Inventory turns over slowly — may indicate slow-moving stock or "
            "overstocking risk."
        )

    return Inventory(
        available=True,
        fiscal_year=fiscal_year or None,
        inventory=Money(cents=inventory_cents),
        cost_of_sales=Money(cents=cost_of_sales_cents),
        turnover=turnover,
        days_inventory_outstanding=dio,
        extraction_confidence=extraction_confidence_raw,
        narrative=narrative,
    )


_IN_GROUPS = [("revenue_operational", "pesalink_inflow"), ("mpesa_inflow",), ("transfer",)]
_IN_LABELS = ["Bank transfers / invoiced", "M-Pesa channel", "Inter-account"]
_IN_KEYS = ["bank_transfers_invoiced", "mpesa_channel", "inter_account"]

_OUT_GROUPS = [
    ("supplier", "supplier_payment"),
    ("operational", "operational_payment"),
    ("payroll",),
    ("loan_repayment",),
    ("tax_payment",),
]
_OUT_LABELS = ["Procurement / COGS", "Operational", "Payroll", "Loan repayments", "Tax (KRA)"]
_OUT_KEYS = ["procurement_cogs", "operational", "payroll", "loan_repayments", "tax_kra"]


def _build_canon_tagged(canonical: Dict) -> List[Dict]:
    """
    Mirrors render_snapshot_html()'s own canon_tagged construction exactly
    (same silent-drop of any row missing txn_date). Both this function and
    the renderer build it independently from the same canonical_json —
    accepted duplication, same pattern as everywhere else in this module.
    """
    canon_role_by_txn: Dict[str, str] = {
        str(m.get("txn_id") or ""): m.get("role", "")
        for m in (canonical.get("txn_entity_map") or [])
    }
    canon_tagged: List[Dict] = []
    for t in canonical.get("transactions") or []:
        txn_date = str(t.get("txn_date") or "")
        if not txn_date:
            continue
        txn_id = str(t.get("id") or t.get("txn_id") or "")
        canon_tagged.append({
            "role": canon_role_by_txn.get(txn_id, ""),
            "amount_cents": int(t.get("signed_amount_cents") or 0),
            "txn_date": txn_date,
            "txn_id": txn_id,
        })
    return canon_tagged


def _build_composition(canon_tagged: List[Dict], currency: str) -> Tuple[Composition, Composition]:
    by_role_in: Dict[str, int] = defaultdict(int)
    total_in = 0
    for t in canon_tagged:
        if t["amount_cents"] > 0 and t["role"] in CASHFLOW_INFLOW_ROLES:
            by_role_in[t["role"]] += t["amount_cents"]
            total_in += t["amount_cents"]

    by_role_out: Dict[str, int] = defaultdict(int)
    total_out = 0
    for t in canon_tagged:
        if t["amount_cents"] < 0:
            amt = abs(t["amount_cents"])
            by_role_out[t["role"]] += amt
            total_out += amt

    inflow_segments: List[Segment] = []
    in_accounted = 0
    for roles, label, key in zip(_IN_GROUPS, _IN_LABELS, _IN_KEYS):
        total = sum(by_role_in.get(r, 0) for r in roles)
        if total > 0 and total_in > 0:
            pct = max(1, int(total / total_in * 100))
            in_accounted += pct
            inflow_segments.append(
                Segment(key=key, label=label, amount=Money(cents=total), share=Percent(value=pct / 100))
            )
    other_in = total_in - sum(by_role_in.get(r, 0) for grp in _IN_GROUPS for r in grp)
    if other_in > 0 and total_in > 0:
        other_pct = max(0, 100 - in_accounted)
        inflow_segments.append(
            Segment(key="other", label="Other / unclassified",
                    amount=Money(cents=other_in), share=Percent(value=other_pct / 100))
        )

    outflow_segments: List[Segment] = []
    out_accounted = 0
    for roles, label, key in zip(_OUT_GROUPS, _OUT_LABELS, _OUT_KEYS):
        total = sum(by_role_out.get(r, 0) for r in roles)
        if total > 0 and total_out > 0:
            pct = max(1, int(total / total_out * 100))
            out_accounted += pct
            outflow_segments.append(
                Segment(key=key, label=label, amount=Money(cents=total), share=Percent(value=pct / 100))
            )
    other_out = total_out - sum(by_role_out.get(r, 0) for grp in _OUT_GROUPS for r in grp)
    if other_out > 0 and total_out > 0:
        other_pct = max(0, 100 - out_accounted)
        outflow_segments.append(
            Segment(key="other", label="Finance charges / other",
                    amount=Money(cents=other_out), share=Percent(value=other_pct / 100))
        )

    mpesa_cents = by_role_in.get("mpesa_inflow", 0)
    mpesa_pct = (mpesa_cents / total_in * 100) if total_in else 0
    mpesa_txn_count = sum(1 for t in canon_tagged if t["role"] == "mpesa_inflow" and t["amount_cents"] > 0)
    mpesa_avg = (mpesa_cents / mpesa_txn_count / 100) if mpesa_txn_count > 0 else 0
    inflow_advisory = (
        f"M-Pesa at {mpesa_txn_count:,} transactions (avg {currency} {mpesa_avg:,.0f} per txn) · "
        "verify consistency with declared business model and customer type · pattern observed, not concluded"
    ) if mpesa_pct > 25 else None

    procurement_cents = sum(by_role_out.get(r, 0) for r in ("supplier", "supplier_payment"))
    procurement_pct = (procurement_cents / total_out * 100) if total_out else 0
    outflow_advisory = (
        f"Procurement outflows ({procurement_pct:.0f}%) — cash procurement controls and cross-border "
        "documentation should be verified · observed supplier payments represent partial COGS visibility"
    ) if procurement_pct > 50 else None

    inflow = Composition(total=Money(cents=total_in, currency=currency), segments=inflow_segments, advisory=inflow_advisory)
    outflow = Composition(total=Money(cents=total_out, currency=currency), segments=outflow_segments, advisory=outflow_advisory)
    return inflow, outflow


def _resolve_recon_status(status_raw: Optional[str], coverage_incomplete: bool) -> ReconStatus:
    """
    Mirrors snapshot_html_renderer._status_to_badge()'s branching exactly
    (minus the class/label — that stays a WeasyPrint presentation concern).
    """
    if status_raw == "EXACT_MATCH":
        return "EXACT_MATCH"
    if status_raw in ("ACCEPTABLE", "ACCEPTABLE_VARIANCE", "HEALTHY"):
        return "ACCEPTABLE"
    if coverage_incomplete:
        return "COVERAGE_GAP"
    return "VARIANCE"


def _build_loan_activity(
    txns: List[Dict],
    in_active_period,
    af: Dict,
    recon_available: bool,
    loans_r: Dict,
    coverage_incomplete: bool,
) -> LoanActivity:
    # No `t["txn_date"]` truthiness guard here, deliberately matching the
    # original exactly — unlike the Tax Compliance loop, the original loan
    # repayment loop calls in_active_period(m) even when m == "" (missing
    # txn_date). Not homogenizing the two; preserving the original as-is.
    repay_months: Dict[str, int] = defaultdict(int)
    for t in txns:
        if t["role"] == "loan_repayment" and t["signed"] < 0:
            m = (t["txn_date"] or "")[:7]
            if in_active_period(m):
                repay_months[m] += 1
    repayments_per_month = (
        sum(repay_months.values()) / len(repay_months) if repay_months else 0
    )
    repayment_txn_count = sum(1 for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0)

    disbursed_cents = sum(
        t["signed"] for t in txns if t["role"] == "loan_disbursement" and t["signed"] > 0
    )
    repaid_cents = sum(
        t["abs"] for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0
    )
    net_cents = disbursed_cents - repaid_cents

    status_raw = (loans_r.get("status") or None) if recon_available else None
    resolved_status = _resolve_recon_status(status_raw or "VARIANCE", coverage_incomplete)

    # Not gated on recon_available: matches the original exactly, which never
    # explicitly checked it here either — af is already {} when
    # recon_available is False (set that way by the caller), so
    # af.get("loan_breakdown") naturally yields [] in that state anyway.
    facilities = [
        LoanFacility(
            name=fac.get("name") or "--",
            amount=Money(cents=int(fac.get("amount_cents") or 0)),
            status=resolved_status,
        )
        for fac in (af.get("loan_breakdown") or [])
    ]

    # Deliberately loans_r.get(key, 0) — NOT `or 0` — matching the original
    # exactly, including its latent behavior: a key present with an explicit
    # None value raises TypeError here, same as the original did. Not
    # silently hardening this; that would be an undocumented behavior change.
    bank_net_cents = int(loans_r.get("bank_net_borrowing_kes", 0) * 100)
    declared_net_cents = int(loans_r.get("declared_net_borrowing_kes", 0) * 100)
    variance_raw = loans_r.get("variance_pct")
    variance = Percent(value=variance_raw / 100) if variance_raw is not None else None

    return LoanActivity(
        disbursed=Money(cents=disbursed_cents),
        repaid=Money(cents=repaid_cents),
        net=Money(cents=net_cents),
        repayments_per_month=repayments_per_month,
        repayment_txn_count=repayment_txn_count,
        facilities=facilities,
        bank_net=Money(cents=bank_net_cents),
        declared_net=Money(cents=declared_net_cents),
        variance=variance,
        status_raw=status_raw,
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


def _build_tax_payment_pattern(txns: List[Dict]) -> TaxPaymentPattern:
    tax_txns = [t for t in txns if t["role"] == "tax_payment" and t["signed"] < 0]
    tax_by_month: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "total": 0})
    for t in tax_txns:
        m = (t["txn_date"] or "")[:7]
        tax_by_month[m]["count"] += 1
        tax_by_month[m]["total"] += t["abs"]

    jan_spike = any(m.endswith("-01") for m in tax_by_month)
    penalty_count = sum(
        1 for t in tax_txns
        if any(k in (t["desc"] or "").upper() for k in _TAX_PENALTY_KEYWORDS)
    )
    tax_total_cents = sum(t["abs"] for t in tax_txns)
    tax_months_count = len(tax_by_month)
    jan_month = next((m for m in tax_by_month if m.endswith("-01")), None)
    jan_total = tax_by_month[jan_month]["total"] if jan_month else 0

    avg_per_month = (len(tax_txns) / tax_months_count) if tax_months_count > 0 else None

    if jan_spike and penalty_count == 0:
        narrative = (
            "Consistent KRA cadence observed across all months. "
            "January spike consistent with prior-year settlement — not a penalty indicator. "
            "Regular PAYE + VAT cadence maintained. "
            "Note: Bank payment regularity observed, not compliance status. Verify certificate independently."
        )
    elif penalty_count > 0:
        narrative = (
            f"{penalty_count} potential penalty transaction(s) detected — "
            "verify KRA compliance certificate independently."
        )
    else:
        narrative = (
            "Regular KRA payment pattern observed. "
            "Note: Bank regularity only — verify compliance certificate independently."
        )

    return TaxPaymentPattern(
        txn_count=len(tax_txns),
        avg_per_month=avg_per_month,
        penalty_count=penalty_count,
        total=Money(cents=tax_total_cents),
        jan_spike=jan_spike,
        jan_spike_total=Money(cents=jan_total) if jan_total > 0 else None,
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
    inventory_config: InventoryConfig = DEFAULT_INVENTORY_CONFIG,
) -> Dict[str, object]:
    """
    PARTIAL — Stage 6 of PAR-189. Returns:
        {"risk": RiskAssessment, "supplier_payments": SupplierPayments,
         "transaction_patterns": TransactionPatterns, "tax_compliance": TaxCompliance,
         "tax_payment_pattern": TaxPaymentPattern,
         "inventory": Inventory, "analyst_notes": Optional[str], "loans": LoanActivity,
         "inflow": Composition, "outflow": Composition}
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

    deal_result = (
        sb.table("pds_deals")
        .select("analyst_notes, currency")
        .eq("id", deal_id)
        .single()
        .execute()
    )
    deal_row: Dict = deal_result.data or {}
    analyst_notes: Optional[str] = deal_row.get("analyst_notes") or None
    currency: str = deal_row.get("currency") or "KES"

    af_result = (
        sb.table("pds_audited_financials")
        .select("financial_year, inventory_cents, cost_of_sales_cents, extraction_confidence, loan_breakdown")
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    recon_available = len(af_result) > 0
    af: Dict = af_result[0] if recon_available else {}
    af_financial_year = af.get("financial_year") if recon_available else None

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

    # Same coverage-incomplete derivation snapshot_html_renderer.py still
    # computes independently for the not-yet-extracted 4-Point Reconciliation
    # section (rev/exp/loan badges there) — reused here, not a new concept,
    # just recomputed from acct_cov_raw which this function already fetches.
    missing_bank_names = [
        a.get("bank_name") for a in (acct_cov_raw.get("account_details") or [])
        if a.get("status") != "SUBMITTED" and a.get("bank_name")
    ]
    coverage_incomplete = recon_available and bool(missing_bank_names)

    loans_r: Dict = (recon_section.get("loan_activity") or {}) if recon_available else {}

    transaction_patterns = _build_transaction_patterns(canonical.get("transactions") or [])

    canon_tagged = _build_canon_tagged(canonical)
    inflow, outflow = _build_composition(canon_tagged, currency)

    txns = _fetch_txns_for_context(sb, deal_id)

    entity_rows = _paginate(sb, "pds_entities", "entity_id, display_name", deal_id)
    entity_name_by_id: Dict[str, str] = {
        e["entity_id"]: e.get("display_name") for e in entity_rows
    }

    supplier_payments = _build_supplier_payments(txns, entity_name_by_id, supplier_config)
    tax_compliance = _build_tax_compliance(txns, in_active_period, tax_config)
    tax_payment_pattern = _build_tax_payment_pattern(txns)
    inventory = _build_inventory(af, recon_available, inventory_config)
    loans = _build_loan_activity(txns, in_active_period, af, recon_available, loans_r, coverage_incomplete)
    risk = _build_risk_assessment(
        txns, recon_tier, acct_cov_raw, transaction_patterns.critical_count, supplier_config,
    )

    return {
        "risk": risk,
        "loans": loans,
        "supplier_payments": supplier_payments,
        "transaction_patterns": transaction_patterns,
        "tax_compliance": tax_compliance,
        "tax_payment_pattern": tax_payment_pattern,
        "inventory": inventory,
        "analyst_notes": analyst_notes,
        "inflow": inflow,
        "outflow": outflow,
    }
