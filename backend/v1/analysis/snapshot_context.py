"""
Shared snapshot-context data layer (PAR-189).

STATUS: partial extraction. Stage 1 covered Risk Assessment Summary and
Supplier Payment Analysis (both already implicated in real content-drop bugs
— PAR-188 and same-night testing respectively). Stage 2 added Transaction
Pattern Analysis and Tax Compliance Analysis. Stage 3 added Analyst Notes and
Inventory Analysis. Stage 4 added Loan Activity Detected and Loan Facilities
(one LoanActivity concept spanning two template sections). Stage 5 added
Inflow Composition and Outflow Composition. Stage 6 added Tax Payment Pattern.
Stage 7 added Inter-Account Transfer Analysis. Stage 8 added Account Coverage.
Stage 9 adds the 4-Point Reconciliation table.
The remaining ~4 sections are still computed inline in
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

Stage 7 note: InterAccountTransfer carries a semantic `state`
(DETECTED / NO_TRANSFERS_FOUND / UNAVAILABLE) rather than the original's
inline badge text ("Detected" / "No Transfers Found" / "Not Available") — the
badge string is presentation and now lives in the WeasyPrint adapter, per
ratified decision #5. The NO_TRANSFERS_FOUND vs UNAVAILABLE distinction is
load-bearing and must never be collapsed: the first means detection ran and
genuinely found nothing, the second means the pre-PAR-102 per-account tagging
gap makes detection structurally impossible. Reporting the second as the
first would be a false negative on a real financial claim.

Stage 8 note: Account Coverage is the first section where ratified decision
#5 does substantial work — the original carried three separate CSS-class
lookup tables inline (advisory tier -> stat colour, materiality -> status
pill, submitted/missing -> status pill) plus a pre-rendered "✓ Submitted"
label. All four are presentation and now live in the WeasyPrint adapter; the
context carries only `Materiality` and `AccountSubmissionStatus` enums.

Stage 8 also found and fixed a REAL latent formatting divergence introduced
by Stage 1, not a hypothetical one: `coverage_pct` reaches this layer already
rounded to hundredths (round(basis_points / 100, 2)), and storing it as a 0-1
`Percent` then multiplying back by 100 to format reintroduces float error.
For 45 of the 10,001 possible basis-point values that changes the rendered
digit (e.g. coverage_pct 0.85 rendered "0.9" instead of the original "0.8").
Stage 1's Risk Assessment adapter had been shipping that divergence since PR
#161; it was invisible to every stage's byte-diff because the Deed document
has no audited financials and renders "--" for coverage on both sides. Both
call sites now format via _fmt_pct_1dp() in snapshot_html_renderer.py,
which re-rounds to hundredths first. See that helper's docstring.

Format-agnostic per PAR-189: nothing returned from this module contains HTML,
CSS class names, hex colours, or markup. Each renderer (WeasyPrint today,
reportlab later) owns its own mapping from these typed values to
presentation — see _supplier_payments_ctx_from() / _risk_assessment_ctx_from()
in snapshot_html_renderer.py for WeasyPrint's adapter.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from ..analytics import CASHFLOW_INFLOW_ROLES, monthly_cashflow as _monthly_cashflow
from ..core.snapshot_engine import decompress_canonical_json_if_needed
from .snapshot_generator import generate_reconciliation_section
from ._snapshot_fetch_helpers import _bank_label, _get_supabase, _paginate

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
TransferDetectionState = Literal["DETECTED", "NO_TRANSFERS_FOUND", "UNAVAILABLE"]
AccountSubmissionStatus = Literal["SUBMITTED", "MISSING"]
ReconCheckKey = Literal["cash_position", "revenue", "expenses", "loan_activity"]

# PAR-207 — gap-waterfall component roles. Semantic only; each renderer owns
# its own kind -> styling map per PAR-189 ratified decision #5.
#   declared  — a figure from the audited financials side
#   observed  — a figure derived from submitted bank data
#   subtotal  — a stated total of the preceding lines of the same side
#   gap       — observed minus declared
#   component — a named amount that bears on the gap, stated WITHOUT any claim
#               that it explains the gap (PAR-150 Rule 4: record the amount,
#               never attach a verdict)
WaterfallKind = Literal["declared", "observed", "subtotal", "gap", "component"]

# Prose shown when audited financials haven't been submitted, so
# calculate_account_coverage() has nothing to compare against. Narrative stays
# a pre-written string per PAR-189 ratified decision #2.
ACCOUNT_COVERAGE_UNAVAILABLE_NOTE = (
    "Account coverage compares the bank accounts declared in audited "
    "financials (Note 11 cash breakdown) against the statements "
    "submitted. Submit audited financials to populate this advisory."
)

# Roles an analyst can apply by override to assert a transaction is a
# self-transfer. Distinct from system detection (pds_transfer_links) —
# see InterAccountTransfer.override_note.
_TRANSFER_ROLES = ("transfer", "internal_transfer")


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
class SupplierEntry:
    """PAR-226: one row of the ranked supplier table. Same per-counterparty
    data _build_supplier_payments() already aggregates into supplier_by_entity
    — this just retains the top N instead of discarding all but the max()."""
    name: str
    txn_count: int
    total: Money
    share: Percent   # this entry's total / supplier_total_cents


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
    top_n: Optional[List[SupplierEntry]] = None   # PAR-226: top 10 by total, all deals


@dataclass(frozen=True)
class CashflowMonthRow:
    month: str            # "YYYY-MM"
    inflow: Money
    outflow: Money
    net: Money             # signed, inflow - outflow
    bar_share: Percent     # 0-1 fraction of this period's max abs(net) — for bar width, not a business metric


@dataclass(frozen=True)
class MonthlyCashflow:
    note: str               # "N of M months net-negative..." / "All M months net-positive." / "No cashflow data available."
    trend_note: str         # "" | one-month caveat | net POSITIVE/NEGATIVE/stable clause (>=2 months only)
    peak_trough_note: str   # "" | "Trough of X in <month>; peak of Y in <month>." (>=2 months only)
    rows: List[CashflowMonthRow]


@dataclass(frozen=True)
class KeyMetricsConfig:
    """
    Both thresholds were hardcoded in the original inline logic; pulled into
    named config per PAR-189 ratified decision #4. Neither is flagged in the
    original as borrowed/unratified, so no PENDING SIGN-OFF caveat applies —
    same footing as TaxComplianceConfig.

    income_quality_threshold is a 0-1 fraction (schema convention). Revenue
    gap deliberately is NOT: rev_gap arrives already rounded to hundredths
    from reconciliation_engine (same class of pre-rounded upstream as the
    4-Point Reconciliation variances Stage 9 found), and the >15 comparison
    in the original runs on that raw, un-round-tripped value. Keeping the
    threshold in the same percentage-point units the comparison actually
    happens in avoids ever needing to round-trip a config value through
    Percent just to compare it — see _build_key_metrics for where the
    decision is made once, on the raw value, and carried as a plain bool.
    """
    income_quality_threshold: float = 0.70
    revenue_gap_warning_threshold_pct: float = 15.0


DEFAULT_KEY_METRICS_CONFIG = KeyMetricsConfig()


@dataclass(frozen=True)
class CashTrend:
    """
    None fields distinguish two genuinely different original states, not one:
    `first_balance is None` -> no balance-bearing transactions at all
    ("balance data unavailable"). `first_balance` set but `yoy is None` ->
    balance data exists but the opening balance was exactly 0, so a
    year-over-year percent is mathematically undefined (division by zero
    guarded in the original) — the sub-line still renders real balances in
    that case, only the headline percent shows "--". Both are real original
    branches, preserved as two independently-nullable signals rather than
    one flattened availability flag.
    """
    yoy: Optional[Percent] = None          # live-computed (NOT pre-rounded upstream) — safe to re-multiply for display
    yoy_positive: Optional[bool] = None    # decided on the raw, unrounded yoy fraction; mirrors yoy's nullness
    first_balance: Optional[Money] = None
    last_balance: Optional[Money] = None


@dataclass(frozen=True)
class KeyMetrics:
    """
    Two mutually exclusive branches gated by `available` (mirrors
    recon_available), same pattern as FourPointReconciliation. Exactly one
    of the two field groups below is populated per instance; the other's
    fields stay None. avg_monthly_revenue is the one metric common to both
    of the original's 4-cell layouts, so it lives outside either group.

    Round-trip-bug audit (PAR-189 Stage 8/9 pattern), done per field, not
    assumed clean or assumed broken:
      - pbt_margin, income_quality: live-computed from raw cents each render,
        never stored pre-rounded anywhere upstream. Multiplying a 0-1 Percent
        back by 100 introduces no divergence here — there is no original
        rounded value to diverge FROM. Rendered with a plain f-string, not
        _fmt_pct_1dp().
      - loan_variance, revenue_gap: sourced from recon_section (the sealed
        reconciliation section) — the SAME pre-rounded-to-hundredths class of
        field the 4-Point Reconciliation variances are. Rendered with
        _fmt_pct_1dp() in the WeasyPrint adapter, matching that precedent
        exactly, not reinventing a second fix for the same bug class.
      - cash_trend.yoy: live-computed from raw balance cents, same footing as
        pbt_margin/income_quality — not pre-rounded upstream.
    Every threshold-driven bool below (pbt_margin_positive,
    income_quality_high, revenue_gap_high, cash_trend.yoy_positive) is
    decided in the builder directly from the RAW, un-round-tripped value,
    never re-derived from the stored Percent downstream — so even the
    live-computed fields carry zero round-trip risk for their color/badge
    decisions, not just their display text.
    """
    available: bool
    avg_monthly_revenue: Money

    # recon_available branch
    pbt_margin: Optional[Percent] = None
    pbt_margin_positive: Optional[bool] = None
    financial_year: Optional[str] = None
    loan_variance: Optional[Percent] = None
    loan_status: Optional[str] = None
    revenue_gap: Optional[Percent] = None
    revenue_gap_high: Optional[bool] = None

    # not-available (observed-only) branch
    income_quality: Optional[Percent] = None
    income_quality_high: Optional[bool] = None
    loan_repayment_freq_per_month: Optional[float] = None
    loan_repayment_txn_count: Optional[int] = None
    cash_trend: Optional[CashTrend] = None


@dataclass(frozen=True)
class ObservedPattern:
    key: str              # stable id — renderer owns tag/item CSS classes, per design doc §2
    name: str
    tag: Literal["Watch", "Observed", "Pattern", "Coverage"]
    data_statement: str
    check_prompt: str


@dataclass(frozen=True)
class ObservedPatterns:
    patterns: List[ObservedPattern]   # already capped at 5, in original priority order


@dataclass(frozen=True)
class TransferPair:
    """
    One detected self-transfer route between two of the company's own accounts.

    `label` is a human route name ("Equity -> KCB"), built from each side's
    detected bank label with the original's exact fallbacks — the document's
    detected bank name, else "Account <first-8-of-document_id>", else a
    positional "Account A"/"Account B". Kept as a single string because that
    is precisely what the original computed and what the template renders; it
    is a name, not a style.
    """
    label: str
    count: int
    total: Money


@dataclass(frozen=True)
class InterAccountTransfer:
    """
    Inter-Account Transfer Analysis (PAR-63, live-checked per PAR-102).

    `state` is the semantic three-way result, NOT a badge string — per PAR-189
    ratified decision #5, each renderer owns its own state -> label mapping
    (WeasyPrint's lives in _inter_account_transfer_ctx_from()). The original
    computed the badge text inline ("Detected" / "No Transfers Found" /
    "Not Available"); that text is presentation and does not belong here.

    The three states are the original's three branches, preserved exactly:
      DETECTED            — real pds_transfer_links rows exist for this deal.
      NO_TRANSFERS_FOUND  — zero links AND 2+ distinct account_id values, i.e.
                            detection genuinely ran and found nothing.
      UNAVAILABLE         — zero links AND <2 distinct account_id values, i.e.
                            the pre-PAR-102 per-account tagging gap. This is an
                            infrastructure limitation, NOT a finding of "no
                            transfers" — the distinction is the whole point of
                            the three-way split and must not be collapsed.

    Per ratified decision #1, the "missing" case carries a null value plus a
    separate reason rather than an overloaded field: `total` is None and
    `pair_count` is 0 for both non-DETECTED states, with `state` carrying the
    reason. Per decision #2, `note`/`override_note` stay as pre-written prose
    (they embed computed figures mid-sentence, the same judgment already
    applied to LoanActivity's and TransactionPatterns' narratives).
    """
    state: TransferDetectionState
    pairs: List[TransferPair]
    pair_count: int                  # 0 unless state == DETECTED
    total: Optional[Money]           # None unless state == DETECTED
    manual_override_count: int
    note: str
    override_note: str


@dataclass(frozen=True)
class ReconCheckConfig:
    """
    The 15% expense-gap acceptability cutoff was hardcoded inline in the
    original (`abs(exp_gap or 0) <= 15`), so it becomes a named config value
    per PAR-189 ratified decision #4. Like TaxComplianceConfig and unlike
    SupplierConcentrationConfig, the original carries no "borrowed / pending
    Parity Science sign-off" marker on it, so no such caveat is attached here
    — only the general carry-as-config rule.

    Note this is a DIFFERENT 15 from reconciliation_engine's own
    `0 <= gap_pct <= 15` revenue banding (line ~391). They are two separate
    hardcoded thresholds that happen to share a value; this config governs
    only the renderer-side expense badge, and deliberately does not reach
    into the engine's own banding.
    """
    expense_acceptable_gap_pct: float = 15.0


DEFAULT_RECON_CHECK_CONFIG = ReconCheckConfig()


@dataclass(frozen=True)
class WaterfallComponent:
    """
    One line of a gap waterfall (PAR-207).

    `amount` is None only for a line that names something with no computable
    figure; renderers show a dash rather than inventing a zero.

    `sub` is a short factual qualifier ("not submitted", "fiscal-year net
    movement") — never an evaluation. Per PAR-150 Rule 4 nothing in this
    dataclass may carry a verdict about whether an amount is good or bad;
    that judgment belongs to the human reader, matching PAR-206's boundary.
    """
    label: str
    amount: Optional[Money]
    kind: WaterfallKind
    sub: Optional[str] = None


@dataclass(frozen=True)
class GapWaterfall:
    """
    A row's declared-vs-observed breakdown (PAR-207).

    `disclosures` carries data-completeness limitations that bear on the
    figures above them — following PAR-209's own precedent of attaching the
    account-coverage advisory to the loan_activity result rather than leaving
    a known gap implicit at the point where it affects a number. These are
    statements of fact about data availability, not interpretations of the
    deal.

    `available=False` means there was not enough in the reconciliation
    section to build a breakdown at all (e.g. an older sealed snapshot
    predating the per-account fields) — the renderer omits the block
    entirely rather than rendering an empty shell.
    """
    available: bool
    components: List[WaterfallComponent] = field(default_factory=list)
    disclosures: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReconCheck:
    """
    One row of the 4-Point Reconciliation table.

    `status` is the semantic 4-way ReconStatus (shared with Stage 4's
    LoanFacility via _resolve_recon_status) — NOT the original's
    (badge_class, badge_label) tuple or its `variance_class`. All three of
    those are CSS and live in the renderer's own table per ratified
    decision #5.

    `variance` is a 0-1 fraction per decision #3. IMPORTANT for renderers:
    the underlying gap_pct/variance_pct values arrive from
    reconciliation_engine already rounded to hundredths, so formatting them
    back to a percentage string requires the re-rounding in
    _fmt_pct_1dp() — see that helper. Naive `value * 100` formatting diverges
    from the original on 748 of the 100,001 values in the plausible
    -500%..+500% range, including negatives, which these fields routinely are.

    `label` / `observed_sub` / `declared_sub` are the row's fixed descriptive
    wording. They stay in the shared context rather than moving to each
    renderer precisely so the two renderers cannot drift on what a row claims
    to be comparing — that divergence risk is the reason this layer exists.
    """
    key: ReconCheckKey
    label: str
    observed: Money
    observed_sub: str
    declared: Money
    declared_sub: str
    variance: Optional[Percent]
    status: ReconStatus
    assessment: str
    # PAR-207 — per-row gap breakdown. None (not an empty GapWaterfall) on rows
    # that have no breakdown, so a renderer can distinguish "this row has no
    # waterfall" from "this row's waterfall came back empty".
    waterfall: Optional["GapWaterfall"] = None


@dataclass(frozen=True)
class FourPointReconciliation:
    """
    4-Point Reconciliation — Declared vs Observed.

    `available` mirrors recon_available: with no audited financials there is
    nothing to reconcile against, and the template renders a separate
    static locked-state section instead (snapshot.html:1448, which reads no
    context at all — see the Stage 9 report).

    Per decision #1 the unavailable case is an empty check list plus
    `fiscal_note=None`, not sentinel rows.
    """
    available: bool
    checks: List[ReconCheck] = field(default_factory=list)
    fiscal_note: Optional[str] = None   # None -> renderer shows "" (original's own default)


@dataclass(frozen=True)
class DeclaredAccount:
    """
    One bank account declared in audited financials (Note 11 cash breakdown),
    and whether a statement for it was actually submitted.

    `status` and `materiality` are semantic values, not the status-pill CSS
    classes the original carried alongside them (`status-matched` /
    `status-missing` / `status-critical`) — per PAR-189 ratified decision #5
    those belong to each renderer's own style table. The original also carried
    a pre-rendered `status_label` ("✓ Submitted" / "Missing"); the tick is
    presentation and now lives in the WeasyPrint adapter.
    """
    bank_name: Optional[str]          # None -> renderer shows "--"
    declared_balance: Money
    status: AccountSubmissionStatus
    materiality: Optional[Materiality]  # None -> renderer shows "--"


@dataclass(frozen=True)
class AccountCoverage:
    """
    Account Coverage — Declared vs Submitted.

    Sourced entirely from `recon_section["account_coverage"]`, which
    build_snapshot_context() already fetches for RiskAssessment (Stage 1) and
    LoanActivity's coverage_incomplete (Stage 4) — this section adds no new
    fetch and no new upstream.

    `available` is False whenever `coverage_pct` is absent, which covers both
    "no audited financials submitted at all" and
    calculate_account_coverage()'s own SKIPPED return (no cash_breakdown in
    the audited financials). Per ratified decision #1 the unavailable case is
    null values plus `unavailable_note` carrying the reason, never sentinel
    strings stuffed into the value fields.

    `coverage` is a 0-1 fraction per decision #3. NOTE for any renderer
    formatting it back to a percentage string: see _fmt_pct_1dp() in
    snapshot_html_renderer.py — the upstream value is an exact hundredth
    (round(basis_points / 100, 2)) and naively multiplying the stored fraction
    by 100 reintroduces float error that changes the rendered digit for 45 of
    the 10,001 possible values. Re-round to hundredths before formatting.
    """
    available: bool
    coverage: Optional[Percent] = None
    advisory_tier: Optional[Materiality] = None
    declared_count: Optional[int] = None
    submitted_count: Optional[int] = None
    missing_count: Optional[int] = None
    missing_balance: Optional[Money] = None
    recommendation: Optional[str] = None
    accounts: List[DeclaredAccount] = field(default_factory=list)
    unavailable_note: Optional[str] = None


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
    null-safe abs derivation). Stage 6 added normalized_descriptor (-> "desc")
    for Tax Payment Pattern's penalty-keyword detection. Stage 7 added "id",
    account_id and document_id, which Inter-Account Transfer Analysis needs to
    count distinct accounts and to name each side of a detected transfer pair.
    Stage 11 added balance_cents (-> "balance", None-safe, matching the
    renderer's own null-safe bal_txns filter), which Key Metrics' Cash Trend
    needs and no earlier section did.
    """
    txn_rows = _paginate(
        sb, "pds_raw_transactions",
        "id, txn_date, signed_amount_cents, abs_amount_cents, normalized_descriptor, "
        "balance_cents, account_id, document_id",
        deal_id,
    )
    map_rows = _paginate(sb, "pds_txn_entity_map", "txn_id, role, entity_id", deal_id)
    role_by_txn = {r["txn_id"]: r["role"] for r in map_rows}
    entity_id_by_txn = {r["txn_id"]: r.get("entity_id") for r in map_rows}

    return [{
        "id": t["id"],
        "txn_date": t["txn_date"],
        "signed": t["signed_amount_cents"] or 0,
        "abs": t["abs_amount_cents"] if t["abs_amount_cents"] is not None else abs(t["signed_amount_cents"] or 0),
        "desc": t["normalized_descriptor"] or "",
        "balance": t.get("balance_cents"),
        "role": role_by_txn.get(t["id"], "other"),
        "entity_id": entity_id_by_txn.get(t["id"]),
        "account_id": t.get("account_id"),
        "document_id": t.get("document_id"),
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


_MONTH_ABBR = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}  # duplicated from snapshot_html_renderer.MONTH_ABBR — same accepted-duplication
   # pattern as _build_canon_tagged; kept local so a prose sentence can be
   # fully assembled here rather than templated in the renderer.


def _build_monthly_cashflow(
    canon_tagged: List[Dict],
    in_active_period,
    currency: str,
) -> MonthlyCashflow:
    """
    Monthly Cashflow (PAR-189 Stage 10), transcribed from three previously-
    separate inline blocks in render_snapshot_html() — "Cashflow net-negative
    months" (cashflow_note), "Monthly Cashflow Pattern (PAR-63)"
    (trend_note/peak_trough_note), and "Monthly cashflow chart rows" (rows).
    All three read the same monthly_merged/period_months derived from
    _monthly_cashflow(canon_tagged) — the original's own comment confirms
    single source, no independent recompute — so they move together here.

    period_months/neg_months are cheap to recompute; the renderer still does
    so locally for Observed Patterns (not yet extracted this stage), same
    accepted-duplication precedent as Stage 9's kms/recon_rows finding — this
    is not a hidden coupling back onto this function.

    No percentage field in this section's original scope is a pre-rounded
    hundredths value being round-tripped through a 0-1 fraction (the
    Stage 8/9 bug pattern) — checked explicitly. bar_pct/bar_share is a
    live ratio (abs(net)/max(abs(net))) computed fresh here every time, never
    stored-then-reformatted elsewhere, and the original's `int(...)`
    truncation (not round()) is preserved exactly in the renderer's
    _monthly_cashflow_ctx_from() to avoid introducing any new rounding
    divergence.
    """
    monthly_merged: Dict[str, Dict[str, int]] = {
        row["month"]: {"inflow_cents": row["inflow_cents"], "outflow_cents": row["outflow_cents"]}
        for row in _monthly_cashflow(canon_tagged)
    }
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
        note = (
            f"{len(neg_months)} of {len(period_months)} months net-negative. "
            f"Largest deficit in {_MONTH_ABBR.get(worst[5:7], worst[5:7])} {worst[:4]}."
        )
    elif period_months:
        note = f"All {len(period_months)} months net-positive."
    else:
        note = "No cashflow data available."

    if len(period_months) < 2:
        trend_note = (
            "Only one month of data is available — a trend cannot yet be established."
            if period_months else ""
        )
        peak_trough_note = ""
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
            trend_note = "The trend over the observed period is net POSITIVE."
        elif last_net < first_net:
            trend_note = "The trend over the observed period is net NEGATIVE — recent months show declining net position."
        else:
            trend_note = "Net position is broadly stable with no clear directional trend."
        peak_trough_note = (
            f"Trough of {_fmt_kes(nets_by_month[trough_month])} in "
            f"{_MONTH_ABBR.get(trough_month[5:7], trough_month[5:7])} {trough_month[:4]}; "
            f"peak of {_fmt_kes(nets_by_month[peak_month])} in "
            f"{_MONTH_ABBR.get(peak_month[5:7], peak_month[5:7])} {peak_month[:4]}."
        )

    max_abs_net = (
        max(abs(monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"])
            for m in period_months)
        if period_months else 1
    ) or 1

    rows: List[CashflowMonthRow] = []
    for m in period_months:
        v = monthly_merged[m]
        net = v["inflow_cents"] - v["outflow_cents"]
        rows.append(CashflowMonthRow(
            month=m,
            inflow=Money(cents=v["inflow_cents"], currency=currency),
            outflow=Money(cents=v["outflow_cents"], currency=currency),
            net=Money(cents=net, currency=currency),
            bar_share=Percent(value=min(abs(net) / max_abs_net, 1.0)),
        ))

    return MonthlyCashflow(
        note=note,
        trend_note=trend_note,
        peak_trough_note=peak_trough_note,
        rows=rows,
    )


_REVENUE_ROLES = {"revenue_operational", "mpesa_inflow", "pesalink_inflow"}
# Mirrors the value snapshot_html_renderer.REVENUE_ROLES held before Stage 11
# — that module-level constant is now dead code there (Key Metrics/Observed
# Patterns were its only readers) and was removed. This is the sole
# remaining copy; no longer a "kept in sync by hand" duplication.


def _build_key_metrics(
    txns: List[Dict],
    canon_tagged: List[Dict],
    in_active_period,
    recon_available: bool,
    af: Dict,
    recon_section: Dict,
    currency: str,
    config: KeyMetricsConfig = DEFAULT_KEY_METRICS_CONFIG,
) -> KeyMetrics:
    """
    Key Metrics (PAR-189 Stage 11), transcribed from the original inline
    "Key metrics (4 cells, different per state)" block in
    render_snapshot_html(). See KeyMetrics' own docstring for the per-field
    round-trip-bug audit — this function is where each of those decisions is
    actually made, once, on raw values.
    """
    # Avg monthly revenue — common to both branches. Independent recompute of
    # the renderer's own by_month_rev loop over the same txns/in_active_period.
    by_month_rev: Dict[str, int] = defaultdict(int)
    for t in txns:
        if t["signed"] > 0 and t["role"] in _REVENUE_ROLES:
            m = (t["txn_date"] or "")[:7]
            if in_active_period(m):
                by_month_rev[m] += t["signed"]
    avg_rev_cents = (
        int(sum(by_month_rev.values()) / len(by_month_rev)) if by_month_rev else 0
    )
    avg_monthly_revenue = Money(cents=avg_rev_cents, currency=currency)

    if recon_available:
        turnover_cents = int(af.get("turnover_cents") or 0)
        pbt_cents = int(af.get("profit_before_tax_cents") or 0)
        pbt_margin_raw = (pbt_cents / turnover_cents * 100) if turnover_cents > 0 else 0

        loans_r = recon_section.get("loan_activity") or {}
        loan_var_pct = loans_r.get("variance_pct")

        rev_r = recon_section.get("revenue") or {}
        rev_gap = rev_r.get("gap_pct")

        return KeyMetrics(
            available=True,
            avg_monthly_revenue=avg_monthly_revenue,
            pbt_margin=Percent(value=pbt_margin_raw / 100),
            pbt_margin_positive=pbt_margin_raw > 0,
            financial_year=str(af.get("financial_year") or ""),
            loan_variance=(
                Percent(value=abs(loan_var_pct) / 100) if loan_var_pct is not None else None
            ),
            loan_status=loans_r.get("status", ""),
            revenue_gap=Percent(value=rev_gap / 100) if rev_gap is not None else None,
            # Decided on the raw, pre-rounded rev_gap directly — never on a
            # value that has been through the 0-1 Percent round trip. See
            # KeyMetricsConfig's docstring for why the threshold stays in
            # percentage-point units rather than becoming a 0-1 fraction.
            revenue_gap_high=(rev_gap or 0) > config.revenue_gap_warning_threshold_pct,
        )

    # ── Not-available (observed-only) branch ─────────────────────────────────
    by_role_in: Dict[str, int] = defaultdict(int)
    total_in = 0
    for t in canon_tagged:
        if t["amount_cents"] > 0 and t["role"] in CASHFLOW_INFLOW_ROLES:
            by_role_in[t["role"]] += t["amount_cents"]
            total_in += t["amount_cents"]
    op_in = sum(v for k, v in by_role_in.items() if k in _REVENUE_ROLES)
    income_quality_raw = (op_in / total_in * 100) if total_in else 0

    repay_months: Dict[str, int] = defaultdict(int)
    for t in txns:
        if t["role"] == "loan_repayment" and t["signed"] < 0:
            m = (t["txn_date"] or "")[:7]
            if in_active_period(m):
                repay_months[m] += 1
    loan_freq = sum(repay_months.values()) / len(repay_months) if repay_months else 0
    loan_repayment_txn_count = sum(
        1 for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0
    )

    bal_txns = sorted(
        [t for t in txns if t.get("balance") is not None],
        key=lambda x: x["txn_date"] or "",
    )
    if bal_txns:
        first_bal = bal_txns[0]["balance"]
        last_bal = bal_txns[-1]["balance"]
        yoy_pct = ((last_bal - first_bal) / abs(first_bal) * 100) if first_bal else None
        cash_trend = CashTrend(
            yoy=Percent(value=yoy_pct / 100) if yoy_pct is not None else None,
            yoy_positive=(yoy_pct is not None and yoy_pct >= 0),
            first_balance=Money(cents=first_bal, currency=currency),
            last_balance=Money(cents=last_bal, currency=currency),
        )
    else:
        cash_trend = CashTrend()

    return KeyMetrics(
        available=False,
        avg_monthly_revenue=avg_monthly_revenue,
        income_quality=Percent(value=income_quality_raw / 100),
        income_quality_high=income_quality_raw >= config.income_quality_threshold * 100,
        loan_repayment_freq_per_month=loan_freq,
        loan_repayment_txn_count=loan_repayment_txn_count,
        cash_trend=cash_trend,
    )


def _build_observed_patterns(
    txns: List[Dict],
    canon_tagged: List[Dict],
    in_active_period,
    credit_scoring_inputs_list: List[Dict],
) -> ObservedPatterns:
    """
    Observed Patterns (PAR-189 Stage 11), transcribed from the original
    inline "Pattern cards" block in render_snapshot_html().

    Every raw aggregate this reads (by_role_in/total_in for M-Pesa
    concentration, monthly_merged/period_months/neg_months for net-negative
    months, payroll_stability_live/n_payroll_months/n_total_months for
    irregular payroll, needs_review_count) is recomputed independently here
    from the same canon_tagged/txns/in_active_period single sources Key
    Metrics and Monthly Cashflow also derive from — this section reads no
    other section's finished dataclass output. Same accepted-duplication
    pattern used throughout PAR-189 rather than threading extra return
    values between builders.

    mpesa_pct is a live ratio (mpesa inflow cents / total inflow cents),
    recomputed fresh here, not a pre-rounded upstream value — no round-trip
    risk, and the >40 threshold decision is made directly on the raw
    percentage, same discipline as Key Metrics' thresholds.
    """
    by_role_in: Dict[str, int] = defaultdict(int)
    total_in = 0
    for t in canon_tagged:
        if t["amount_cents"] > 0 and t["role"] in CASHFLOW_INFLOW_ROLES:
            by_role_in[t["role"]] += t["amount_cents"]
            total_in += t["amount_cents"]
    mpesa_cents = by_role_in.get("mpesa_inflow", 0)
    mpesa_pct = (mpesa_cents / total_in * 100) if total_in else 0

    monthly_merged: Dict[str, Dict[str, int]] = {
        row["month"]: {"inflow_cents": row["inflow_cents"], "outflow_cents": row["outflow_cents"]}
        for row in _monthly_cashflow(canon_tagged)
    }
    period_months = sorted(m for m in monthly_merged if in_active_period(m))
    neg_months = sorted(
        m for m in period_months
        if (monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"]) < 0
    )

    all_months_active: set = set()
    payroll_months_active: set = set()
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

    patterns: List[ObservedPattern] = []

    if mpesa_pct > 40:
        patterns.append(ObservedPattern(
            key="mpesa_concentration",
            name="M-Pesa concentration",
            tag="Watch",
            data_statement=f"M-Pesa inflows represent {mpesa_pct:.1f}% of total observed inflows",
            check_prompt="→ Review: consistent with declared customer mix and B2B model?",
        ))

    for cs in credit_scoring_inputs_list:
        if cs.get("kra_compliance") == "GAPS_DETECTED":
            patterns.append(ObservedPattern(
                key="tax_payment_gap",
                name="Tax payment gap",
                tag="Observed",
                data_statement=cs.get("kra_note") or "Tax payment gaps detected",
                check_prompt="→ Review: gap months explained by filing schedule or missed payments?",
            ))
            break

    if payroll_stability_live == "IRREGULAR":
        patterns.append(ObservedPattern(
            key="irregular_payroll",
            name="Irregular payroll",
            tag="Pattern",
            data_statement=f"Payroll detected in {n_payroll_months} of {n_total_months} months",
            check_prompt="→ Review: casual workforce or payroll routed off-statement?",
        ))

    if len(neg_months) > 2:
        label_months = ", ".join(
            _MONTH_ABBR.get(m[5:7], m[5:7]) for m in neg_months[:3]
        ) + ("..." if len(neg_months) > 3 else "")
        patterns.append(ObservedPattern(
            key="net_negative_months",
            name="Net-negative months",
            tag="Pattern",
            data_statement=f"{len(neg_months)} of {len(period_months)} months net-negative: {label_months}",
            check_prompt="→ Review: seasonal pattern or sustained cash drain?",
        ))

    if needs_review_count > 100:
        patterns.append(ObservedPattern(
            key="analyst_classification_pending",
            name="Analyst classification pending",
            tag="Coverage",
            data_statement=f"{needs_review_count} transactions flagged needs_review",
            check_prompt="→ Review: resolve in Parity dashboard before finalising snapshot.",
        ))

    return ObservedPatterns(patterns=patterns[:5])


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
        # PAR-226: was "Supplier spend is well-diversified across
        # counterparties." — interpretive language, not disclosure (PAR-150).
        # Replaced with the same figure already shown in the table, stated as
        # a plain fact — the reviewer decides what "diversified" means from
        # the number, not from an adjective this system supplies for them.
        concentration = "DIVERSIFIED"
        narrative = (
            f"Top supplier accounts for {top_supplier_share * 100:.1f}% of "
            f"total supplier spend across {supplier_entity_count} counterparties."
        )

    # PAR-226: top-10 by total value, for every deal regardless of size —
    # confirmed as a safe default, not a large-deal-only safeguard, pending
    # real data at materially larger supplier counts than observed so far.
    ranked = sorted(supplier_by_entity.items(), key=lambda kv: kv[1]["total"], reverse=True)
    top_n = [
        SupplierEntry(
            name=(
                entity_name_by_id.get(eid)
                or (eid[:16] + "…" if len(eid) > 16 else eid)
                or "--"
            ),
            txn_count=data["count"],
            total=Money(cents=data["total"]),
            share=Percent(value=data["total"] / supplier_total_cents),
        )
        for eid, data in ranked[:10]
    ]

    return SupplierPayments(
        available=True,
        total=Money(cents=supplier_total_cents),
        txn_count=supplier_txn_count,
        counterparty_count=supplier_entity_count,
        top_counterparty=top_supplier_name,
        top_share=Percent(value=top_supplier_share),
        concentration=concentration,
        narrative=narrative,
        top_n=top_n,
    )


def _build_inter_account_transfer(
    txns: List[Dict],
    transfer_link_rows: List[Dict],
    doc_bank_by_id: Dict[Optional[str], Optional[str]],
    currency: str,
) -> InterAccountTransfer:
    """
    Inter-Account Transfer Analysis (PAR-63; live-checked per PAR-102).

    Transcribed from the original inline block in render_snapshot_html().
    Two fidelity points preserved deliberately rather than "cleaned up":

    1. The DETECTED branch is gated on `transfer_link_rows` being truthy
       ALONE — it does not also require 2+ distinct account_ids. So a deal
       carrying real transfer_links while still having degenerate account_id
       tagging renders the real breakdown, not the limitation stub. That
       ordering is the original's and is preserved exactly.

    2. `manual_override_count` (analyst-asserted self-transfers, by role) is
       computed and reported completely independently of system detection —
       the override note renders in all three states, and a deal can have
       analyst overrides while system detection reports UNAVAILABLE. These are
       two different claims about the same deal and the original keeps them
       separate on purpose; collapsing them would overstate what was detected.
    """
    manual_override_count = sum(1 for t in txns if t["role"] in _TRANSFER_ROLES)

    if manual_override_count > 0:
        override_note = (
            f"{manual_override_count} transaction(s) were manually flagged by an analyst "
            "as self-transfers via override — see the Overrides section. This is "
            "analyst-asserted, not system-detected, and does not reflect automatic "
            "self-transfer/cash-sweep detection."
        )
    else:
        override_note = "No transactions have been manually flagged as self-transfers for this deal."

    document_id_by_txn: Dict[str, Optional[str]] = {t["id"]: t.get("document_id") for t in txns}
    distinct_account_ids = {t.get("account_id") for t in txns if t.get("account_id")}

    def _account_label(txn_id: str, fallback: str) -> str:
        doc_id = document_id_by_txn.get(txn_id)
        return doc_bank_by_id.get(doc_id) or (f"Account {doc_id[:8]}" if doc_id else fallback)

    if transfer_link_rows:
        pair_count = len(transfer_link_rows)
        total_cents = sum(l["abs_amount_cents"] for l in transfer_link_rows)
        pair_agg: Dict[str, Dict[str, int]] = defaultdict(lambda: {"count": 0, "cents": 0})
        for link in transfer_link_rows:
            out_label = _account_label(link["txn_out_id"], "Account A")
            in_label = _account_label(link["txn_in_id"], "Account B")
            key = f"{out_label} -> {in_label}"
            pair_agg[key]["count"] += 1
            pair_agg[key]["cents"] += link["abs_amount_cents"]
        pairs = [
            TransferPair(label=key, count=agg["count"], total=Money(agg["cents"], currency))
            for key, agg in sorted(pair_agg.items())
        ]
        note = (
            f"{pair_count} inter-account transfer pair(s) detected between this company's own "
            f"bank accounts, totaling {_fmt_kes(total_cents)}. Detected automatically by pairing "
            "same-amount, opposite-sign transactions across different accounts within a short "
            "window — see the breakdown above."
        )
        return InterAccountTransfer(
            state="DETECTED",
            pairs=pairs,
            pair_count=pair_count,
            total=Money(total_cents, currency),
            manual_override_count=manual_override_count,
            note=note,
            override_note=override_note,
        )

    if len(distinct_account_ids) >= 2:
        note = (
            "Self-transfer / cash-sweep detection ran for this deal — transactions are tagged "
            "with distinct per-account identifiers — and found no qualifying inter-account "
            "transfer pairs in this period. This is a genuine result, not an infrastructure gap."
        )
        state: TransferDetectionState = "NO_TRANSFERS_FOUND"
    else:
        note = (
            "Self-transfer / cash-sweep analysis between this company's own bank accounts "
            "is not currently available. Detection depends on each transaction being tagged "
            "with the specific account it belongs to, and that per-account tagging is not "
            "yet populated correctly in the current ingestion pipeline — every transaction "
            "currently resolves to the same undifferentiated account value, so the matching "
            "logic cannot distinguish between a company's own accounts. This is a known "
            "infrastructure gap, not a finding that no such transfers exist."
        )
        state = "UNAVAILABLE"

    return InterAccountTransfer(
        state=state,
        pairs=[],
        pair_count=0,
        total=None,
        manual_override_count=manual_override_count,
        note=note,
        override_note=override_note,
    )


def _kes_to_money(kes_value, currency: str) -> Money:
    """
    The recon_section sub-dicts carry KES floats, not cents. The original
    converted with int(value * 100) — truncation toward zero, NOT rounding.
    Preserved exactly; switching to round() here would shift half-cent values.
    """
    return Money(int((kes_value or 0) * 100), currency)


def _money_from_entry(entry: Dict, cents_key: str, kes_key: str, currency: str) -> Money:
    """
    Prefer the exact integer-cents field; fall back to the KES float only when
    an older sealed snapshot predates it. _kes_to_money()'s truncation is
    deliberate (see its docstring) — reusing it keeps the fallback path
    byte-identical to how every other KES float in this module is converted.
    """
    cents = entry.get(cents_key)
    if cents is not None:
        return Money(int(cents), currency)
    return _kes_to_money(entry.get(kes_key), currency)


def _build_cash_position_waterfall(
    cash_r: Dict,
    acct_cov_raw: Dict,
    currency: str,
) -> GapWaterfall:
    """
    Cash Position gap waterfall (PAR-207).

    Reflects what `calculate_cash_position_reconciliation()` ACTUALLY computes
    today, not the method its labels imply. Verified against live prod
    2026-08-31: `balance_cents` is NULL on all 193,327 rows of
    pds_raw_transactions, so the "balance_column" primary path — the last
    statement balance on or before fiscal year-end — never executes for any
    deal. Every deal falls through to `flow_derived`, whose per-statement
    figure is the fiscal-year NET MOVEMENT, not a closing balance. That is
    disclosed here rather than corrected: fixing it is a separate, unscoped
    change (PAR-207 explicitly says disclose, don't fix).

    Per-account submitted/missing status is read from the account-coverage
    result that `generate_reconciliation_section()` already computed — this
    builder never re-derives bank-name matching, so it cannot drift from the
    Account Coverage section's own answer.
    """
    declared_entries = cash_r.get("declared_balances") or []
    observed_entries = cash_r.get("bank_balances") or []
    if not declared_entries and not observed_entries:
        return GapWaterfall(available=False)

    status_by_bank: Dict[str, str] = {
        a.get("bank_name"): a.get("status")
        for a in (acct_cov_raw.get("account_details") or [])
        if a.get("bank_name")
    }

    components: List[WaterfallComponent] = []

    for entry in declared_entries:
        name = entry.get("account") or "--"
        status = status_by_bank.get(name)
        components.append(WaterfallComponent(
            label=name,
            amount=_money_from_entry(entry, "balance_cents", "balance_kes", currency),
            kind="declared",
            sub=({"SUBMITTED": "statement submitted",
                  "MISSING": "no statement submitted"}.get(status)),
        ))
    declared_total_money: Optional[Money] = None
    if cash_r.get("total_declared_kes") is not None:
        declared_total_money = _kes_to_money(cash_r.get("total_declared_kes"), currency)
        components.append(WaterfallComponent(
            label="Declared total",
            amount=declared_total_money,
            kind="subtotal",
            sub="Note 11 · cash and equivalents",
        ))

    for entry in observed_entries:
        method = entry.get("method")
        components.append(WaterfallComponent(
            label=entry.get("source") or "--",
            amount=_money_from_entry(entry, "balance_cents", "balance_kes", currency),
            kind="observed",
            sub=("fiscal-year net movement" if method == "flow_derived"
                 else ("statement balance" if method == "balance_column" else None)),
        ))
    if cash_r.get("total_bank_kes") is not None:
        components.append(WaterfallComponent(
            label="Observed total",
            amount=_kes_to_money(cash_r.get("total_bank_kes"), currency),
            kind="subtotal",
            sub="Submitted statements",
        ))

    if cash_r.get("variance_kes") is not None:
        components.append(WaterfallComponent(
            label="Observed less declared",
            amount=_kes_to_money(cash_r.get("variance_kes"), currency),
            kind="gap",
        ))

    # Attribute what IS attributable: the declared balance sitting in accounts
    # for which no statement was provided. Stated as its own amount — NOT as
    # "the cause of the gap", which would be a verdict and, on the real Buildex
    # deal, factually wrong (missing accounts hold KES 266,473 declared while
    # observed EXCEEDS declared by KES 24,238).
    missing_cents = acct_cov_raw.get("missing_balance_cents")
    missing_count = acct_cov_raw.get("missing_accounts_count") or 0
    if missing_cents:
        components.append(WaterfallComponent(
            label="Declared balance in accounts with no statement submitted",
            amount=Money(int(missing_cents), currency),
            kind="component",
            sub=f"{missing_count} of {acct_cov_raw.get('declared_accounts_count') or 0} declared accounts · not verified against bank data",
        ))

    disclosures: List[str] = []

    # The per-account figures come from the audited financials' cash_breakdown
    # note; the declared total comes from the cash-and-equivalents line. They
    # are two separately extracted figures and can differ (on the real Buildex
    # deal they differ by KES 1). Stating the difference keeps the block
    # internally honest instead of showing lines that visibly do not sum.
    if declared_total_money is not None and declared_entries:
        per_account_total = sum(
            (c.amount.cents for c in components
             if c.kind == "declared" and c.amount is not None),
            0,
        )
        drift = per_account_total - declared_total_money.cents
        if drift:
            disclosures.append(
                f"Per-account declared balances sum to "
                f"{_fmt_kes(per_account_total)}, against a declared total of "
                f"{_fmt_kes(declared_total_money.cents)} — a difference of "
                f"{_fmt_kes(abs(drift))}. The two are extracted from different "
                f"lines of the audited financials."
            )

    if cash_r.get("method") == "flow_derived" or any(
        e.get("method") == "flow_derived" for e in observed_entries
    ):
        disclosures.append(
            "Observed figures are each statement's net movement across the fiscal "
            "year, not its closing balance: per-transaction running balances are "
            "not stored for this deal, so a closing balance cannot be read. A net "
            "movement and a closing balance are different quantities."
        )
    if missing_cents:
        disclosures.append(
            "Accounts with no statement submitted contribute to the declared total "
            "but cannot contribute to the observed total."
        )
    return GapWaterfall(available=True, components=components, disclosures=disclosures)


def _build_revenue_waterfall(
    rev_r: Dict,
    af: Dict,
    transfer_state: Optional[TransferDetectionState],
    currency: str,
) -> GapWaterfall:
    """
    Revenue gap waterfall (PAR-207).

    Components are the accrual-timing figures the data model already holds
    (trade and other receivables). They are stated as amounts standing beside
    the gap — never as its explanation, per PAR-150 Rule 4.

    The transfer disclosure is driven off the deal's REAL detection state
    rather than hardcoded, so it stays accurate if PAR-102 is ever fixed.
    Verified against live prod 2026-08-31: 0 transactions carry a
    transfer/internal_transfer role, 0 rows exist in pds_transfer_links, and 0
    deals have more than one distinct account_id — so this resolves to
    UNAVAILABLE, and the disclosure renders, on every deal currently in the
    system. That universality is exactly why it is disclosed at the point of
    the number rather than left implicit (PAR-209's precedent).
    """
    declared_kes = rev_r.get("declared_revenue_kes")
    observed_kes = rev_r.get("bank_inflows_kes")
    if declared_kes is None and observed_kes is None:
        return GapWaterfall(available=False)

    components: List[WaterfallComponent] = [
        WaterfallComponent(
            label="Declared turnover",
            amount=_kes_to_money(declared_kes, currency),
            kind="declared",
            sub="Audited income statement",
        ),
        WaterfallComponent(
            label="Observed operational inflows",
            amount=_kes_to_money(observed_kes, currency),
            kind="observed",
            sub="Bank credits classified as operational revenue",
        ),
    ]
    if rev_r.get("gap_kes") is not None:
        components.append(WaterfallComponent(
            label="Declared less observed",
            amount=_kes_to_money(rev_r.get("gap_kes"), currency),
            kind="gap",
        ))

    for label, field_name, sub in (
        ("Trade receivables outstanding at year-end", "trade_receivables_cents",
         "Audited balance sheet · revenue recognised, cash not yet received"),
        ("Other receivables at year-end", "other_receivables_cents",
         "Audited balance sheet"),
    ):
        cents = af.get(field_name)
        if cents:
            components.append(WaterfallComponent(
                label=label,
                amount=Money(int(cents), currency),
                kind="component",
                sub=sub,
            ))

    disclosures: List[str] = []
    if transfer_state == "UNAVAILABLE":
        disclosures.append(
            "Observed inflows are not net of inter-account transfers: transfer "
            "detection cannot run for this deal, so a transfer between the "
            "company's own accounts that was classified as operational revenue "
            "remains counted here. See PAR-102."
        )
    elif transfer_state == "DETECTED":
        disclosures.append(
            "Observed inflows count bank credits classified as operational "
            "revenue. Transfers detected between the company's own accounts are "
            "classified separately and are not included in this figure."
        )
    elif transfer_state == "NO_TRANSFERS_FOUND":
        disclosures.append(
            "Transfer detection ran for this deal and found no transfers between "
            "the company's own accounts."
        )
    return GapWaterfall(available=True, components=components, disclosures=disclosures)


def _build_four_point_reconciliation(
    recon_section: Dict,
    recon_available: bool,
    coverage_incomplete: bool,
    missing_note: str,
    fy,
    currency: str,
    config: ReconCheckConfig = DEFAULT_RECON_CHECK_CONFIG,
    # PAR-207 — inputs for the per-row gap waterfalls. Optional and trailing so
    # every existing caller keeps working unchanged; when omitted, the rows
    # simply carry waterfall=None and nothing new renders. Both are already
    # resolved at the build_snapshot_context() call site, so wiring them
    # through costs no additional fetch.
    acct_cov_raw: Optional[Dict] = None,
    af: Optional[Dict] = None,
    transfer_state: Optional[TransferDetectionState] = None,
) -> FourPointReconciliation:
    """
    4-Point Reconciliation (PAR-189 Stage 9), transcribed from the original
    inline block in render_snapshot_html().

    Four fidelity points preserved deliberately:

    1. **Cash position is never coverage-softened.** The original calls
       _status_to_badge(cash_status) with NO coverage_incomplete argument,
       while the other three pass it. That is deliberate and documented in
       the original: the declared Note 11 balance is the company's own
       attestation of total cash, so a variance there is genuinely
       unexplained regardless of which statements are missing. Here that
       becomes _resolve_recon_status(..., coverage_incomplete=False).
       Cash also never gets missing_note appended to its assessment.

    2. **Each row derives its status differently**, and the differences are
       real, not incidental:
         - cash  : raw `status` field, no coverage softening
         - revenue: parsed out of the free-text `assessment` string by
                    substring match ("HEALTHY" / "WARNING" / "RISK"), NOT
                    from any status field
         - expenses: purely from the gap magnitude vs the config threshold;
                     the sub-dict's own status field is ignored entirely
         - loan  : raw `status` field, defaulting to "VARIANCE" when absent
       Unifying these onto one rule would silently change badge outcomes.

    3. **`abs()` in the assessment strings is applied to the raw
       already-rounded value**, formatted here in the builder, so it never
       makes the 0-1 round trip. Only ReconCheck.variance does, and the
       renderer must use _fmt_pct_1dp() for it.

    4. **Assessments append missing_note only when the resolved status is
       COVERAGE_GAP**, matching the original's `if badge[0] == "b-warn"`.
    """
    if not recon_available:
        return FourPointReconciliation(available=False)

    cash_r: Dict = recon_section.get("cash_position") or {}
    rev_r: Dict = recon_section.get("revenue") or {}
    exp_r: Dict = recon_section.get("expenses") or {}
    loan_r: Dict = recon_section.get("loan_activity") or {}

    fiscal_note: Optional[str] = None
    fp = rev_r.get("fiscal_period") or ""
    if " to " in fp:
        end_date = fp.split(" to ")[-1]
        fiscal_note = f"All checks at fiscal year-end {end_date}"
    elif fy:
        fiscal_note = f"All checks at fiscal year-end Dec 31 {fy}"

    def _with_missing_note(text: str, status: ReconStatus) -> str:
        if status == "COVERAGE_GAP":
            return f"{text.rstrip('.')} {missing_note}"
        return text

    checks: List[ReconCheck] = []

    # PAR-207: waterfalls are built for Revenue and Cash position only. The
    # Loan activity row is deliberately left without one until PAR-211's
    # Parity Science scoping resolves what that row is supposed to measure for
    # asset-finance-heavy borrowers — building a detailed breakdown on a
    # definition still under review would present an unresolved question as
    # settled. Expenses is unchanged: its declared side is a single stated
    # total with no per-component figures behind it in the data model.
    _acct_cov_raw: Dict = acct_cov_raw or {}
    _af: Dict = af or {}

    # PAR-116: row ORDER is Revenue, Expenses, Loan activity, Cash position —
    # per the ontology's own framing of revenue as the central signal of
    # business health (four-act restructure, Act 2). Each block below still
    # computes its status/assessment exactly as before (point 2's per-row
    # derivation differences are untouched); only the append order changed.

    # ── Revenue — status parsed out of the free-text assessment (point 2) ────
    rev_gap = rev_r.get("gap_pct")
    rev_text = rev_r.get("assessment") or ""
    rev_status_raw = (
        "HEALTHY" if "HEALTHY" in rev_text
        else ("ACCEPTABLE" if "WARNING" not in rev_text and "RISK" not in rev_text else "VARIANCE")
    )
    rev_status = _resolve_recon_status(rev_status_raw, coverage_incomplete)
    checks.append(ReconCheck(
        key="revenue",
        label="Revenue",
        observed=_kes_to_money(rev_r.get("bank_inflows_kes", 0), currency),
        observed_sub="Net operational inflows",
        declared=_kes_to_money(rev_r.get("declared_revenue_kes", 0), currency),
        declared_sub="Declared turnover",
        variance=Percent(rev_gap / 100) if rev_gap is not None else None,
        status=rev_status,
        assessment=_with_missing_note(rev_text or "--", rev_status),
        waterfall=_build_revenue_waterfall(rev_r, _af, transfer_state, currency),
    ))

    # ── Expenses — status purely from gap magnitude vs config (point 2) ──────
    exp_gap = exp_r.get("gap_pct")
    exp_status_raw = (
        "ACCEPTABLE" if abs(exp_gap or 0) <= config.expense_acceptable_gap_pct else "VARIANCE"
    )
    exp_status = _resolve_recon_status(exp_status_raw, coverage_incomplete)
    checks.append(ReconCheck(
        key="expenses",
        label="Expenses",
        observed=_kes_to_money(exp_r.get("bank_outflows_kes", 0), currency),
        observed_sub="Net operational outflows",
        declared=_kes_to_money(exp_r.get("declared_expenses_kes", 0), currency),
        declared_sub="Total declared expenses",
        variance=Percent(exp_gap / 100) if exp_gap is not None else None,
        status=exp_status,
        assessment=_with_missing_note(exp_r.get("explanation") or "--", exp_status),
    ))

    # ── Loan activity ────────────────────────────────────────────────────────
    loan_var = loan_r.get("variance_pct")
    loan_status_raw = loan_r.get("status") or "VARIANCE"
    loan_status = _resolve_recon_status(loan_status_raw, coverage_incomplete)
    if loan_status_raw == "EXACT_MATCH":
        loan_assessment = "Net borrowing matches cashflow statement exactly."
    elif loan_var is not None:
        loan_assessment = f"{abs(loan_var):.1f}% variance — review facility discrepancy."
    else:
        loan_assessment = loan_r.get("reason") or "Insufficient data."
    checks.append(ReconCheck(
        key="loan_activity",
        label="Loan activity",
        observed=_kes_to_money(loan_r.get("bank_net_borrowing_kes", 0), currency),
        observed_sub="Net borrowings · bank-detected",
        declared=_kes_to_money(loan_r.get("declared_net_borrowing_kes", 0), currency),
        declared_sub="Cashflow statement · Note 14",
        variance=Percent(loan_var / 100) if loan_var is not None else None,
        status=loan_status,
        assessment=_with_missing_note(loan_assessment, loan_status),
    ))

    # ── Cash position — deliberately NOT coverage-softened (point 1) ─────────
    cash_var = cash_r.get("variance_pct")
    cash_status_raw = cash_r.get("status") or "SKIPPED"
    cash_status = _resolve_recon_status(cash_status_raw, False)
    if cash_status_raw == "EXACT_MATCH":
        cash_assessment = "On submitted accounts: KES 0 variance."
    elif cash_var is not None:
        cash_assessment = f"{abs(cash_var):.1f}% variance on submitted accounts."
    else:
        cash_assessment = cash_r.get("reason") or "Insufficient data."
    checks.append(ReconCheck(
        key="cash_position",
        label="Cash position",
        observed=_kes_to_money(cash_r.get("total_bank_kes", 0), currency),
        observed_sub="Bank accounts at fiscal year-end",
        declared=_kes_to_money(cash_r.get("total_declared_kes", 0), currency),
        declared_sub="Note 11 · cash and equivalents",
        variance=Percent(cash_var / 100) if cash_var is not None else None,
        status=cash_status,
        assessment=cash_assessment,
        waterfall=_build_cash_position_waterfall(cash_r, _acct_cov_raw, currency),
    ))

    return FourPointReconciliation(available=True, checks=checks, fiscal_note=fiscal_note)


def _build_account_coverage(acct_cov_raw: Dict, currency: str) -> AccountCoverage:
    """
    Account Coverage — Declared vs Submitted (PAR-189 Stage 8).

    Transcribed from the original inline block in render_snapshot_html().
    Fidelity points preserved deliberately:

    1. The available/unavailable branch keys off `coverage_pct is not None` —
       NOT off recon_available, and not off the dict being non-empty.
       calculate_account_coverage() can return {"status": "SKIPPED", ...} when
       the audited financials carry no cash_breakdown; that dict is truthy but
       has no coverage_pct, and the original correctly renders the locked
       state for it. Keying off anything else would flip that case.

    2. `bank_name` and `materiality` use `or`-style fallbacks in the original
       (falsy -> "--"), while `advisory_tier` and `recommendation` use
       `.get(key, default)` (absent -> default, but present-and-None would
       fall through as None). For every dict calculate_account_coverage() can
       actually produce, all four keys are present and non-empty whenever
       coverage_pct is present, so the two forms cannot diverge on real data.
       They are carried here as plain Optionals with the renderer applying the
       "--"/"" fallback, which reproduces the original for every reachable
       input. The only behaviour this normalises is a legacy/corrupt sealed
       recon_section carrying an explicit None, where the original would have
       rendered the literal string "None" into a partner-facing document.
    """
    if acct_cov_raw.get("coverage_pct") is None:
        return AccountCoverage(
            available=False,
            unavailable_note=ACCOUNT_COVERAGE_UNAVAILABLE_NOTE,
        )

    accounts = [
        DeclaredAccount(
            bank_name=a.get("bank_name") or None,
            declared_balance=Money(int(a.get("declared_balance_cents") or 0), currency),
            status="SUBMITTED" if a.get("status") == "SUBMITTED" else "MISSING",
            materiality=a.get("materiality") or None,
        )
        for a in (acct_cov_raw.get("account_details") or [])
    ]

    return AccountCoverage(
        available=True,
        coverage=Percent(value=acct_cov_raw["coverage_pct"] / 100),
        advisory_tier=acct_cov_raw.get("advisory_tier") or None,
        declared_count=acct_cov_raw.get("declared_accounts_count", 0),
        submitted_count=acct_cov_raw.get("submitted_accounts_count", 0),
        missing_count=acct_cov_raw.get("missing_accounts_count", 0),
        missing_balance=Money(int(acct_cov_raw.get("missing_balance_cents") or 0), currency),
        recommendation=acct_cov_raw.get("recommendation") or None,
        accounts=accounts,
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
    recon_check_config: ReconCheckConfig = DEFAULT_RECON_CHECK_CONFIG,
) -> Dict[str, object]:
    """
    Stage 11 of PAR-189 — the last stage. Returns:
        {"risk": RiskAssessment, "supplier_payments": SupplierPayments,
         "transaction_patterns": TransactionPatterns, "tax_compliance": TaxCompliance,
         "tax_payment_pattern": TaxPaymentPattern,
         "inventory": Inventory, "analyst_notes": Optional[str], "loans": LoanActivity,
         "inflow": Composition, "outflow": Composition,
         "inter_account_transfer": InterAccountTransfer,
         "account_coverage": AccountCoverage,
         "four_point_reconciliation": FourPointReconciliation,
         "monthly_cashflow": MonthlyCashflow,
         "key_metrics": KeyMetrics,
         "observed_patterns": ObservedPatterns}
    All ~19 sections render_snapshot_html() renders are now covered by this
    function or genuinely need no extraction (the locked reconciliation
    section is pure static markup — see the Stage 9 report). This is NOT yet
    the full 57-key SnapshotContext from docs/PAR-189-shared-context-schema.md
    — some of the ~60 individual context keys the template reads (report
    metadata, tier badge, doc pills, period label, QR code) are still
    presentation-only or genuinely renderer-local and were never in scope for
    this extraction; see the PAR-189 Stage 11 report for the final accounting.

    This function does its own independent deal/txn/recon fetch rather than
    being fed data already fetched by render_snapshot_html() — see the
    PAR-189 report for why that duplication exists and what it means for
    render_snapshot_html() itself (a separate, not-yet-started piece of work).
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
        .select(
            "financial_year, inventory_cents, cost_of_sales_cents, extraction_confidence, "
            "loan_breakdown, turnover_cents, profit_before_tax_cents"
        )
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

    # PAR-189 Stage 9: this derivation is no longer duplicated in
    # snapshot_html_renderer.py — 4-Point Reconciliation was the last consumer
    # of the renderer's own copy, so missing_bank_names / coverage_incomplete /
    # missing_note now live here only.
    missing_bank_names = [
        a.get("bank_name") for a in (acct_cov_raw.get("account_details") or [])
        if a.get("status") != "SUBMITTED" and a.get("bank_name")
    ]
    coverage_incomplete = recon_available and bool(missing_bank_names)
    missing_note = (
        f"Coverage gap — {', '.join(missing_bank_names)} not submitted."
        if coverage_incomplete else ""
    )

    loans_r: Dict = (recon_section.get("loan_activity") or {}) if recon_available else {}

    transaction_patterns = _build_transaction_patterns(canonical.get("transactions") or [])

    canon_tagged = _build_canon_tagged(canonical)
    inflow, outflow = _build_composition(canon_tagged, currency)
    monthly_cashflow = _build_monthly_cashflow(canon_tagged, in_active_period, currency)

    txns = _fetch_txns_for_context(sb, deal_id)

    entity_rows = _paginate(sb, "pds_entities", "entity_id, display_name", deal_id)
    entity_name_by_id: Dict[str, str] = {
        e["entity_id"]: e.get("display_name") for e in entity_rows
    }

    # PAR-189 Stage 7 — Inter-Account Transfer Analysis. Needs two fetches no
    # earlier stage required: pds_transfer_links (system-detected pairs) and
    # pds_documents (to name each side of a pair by its detected bank label).
    # Stage 11 widened the document select to add "analytics" — Observed
    # Patterns' "Tax payment gap" card needs each document's cached
    # credit_scoring_inputs blob, and this fetch is already deal-scoped and
    # unfiltered, so extending it here avoids a second pds_documents round
    # trip rather than adding one.
    transfer_link_rows: List[Dict] = (
        sb.table("pds_transfer_links")
        .select("txn_out_id, txn_in_id, abs_amount_cents")
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    transfer_doc_rows: List[Dict] = (
        sb.table("pds_documents")
        .select("id, storage_url, source_files, analytics")
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    doc_bank_by_id: Dict[Optional[str], Optional[str]] = {}
    credit_scoring_inputs_list: List[Dict] = []
    for doc in transfer_doc_rows:
        bank_name = _bank_label(doc.get("storage_url") or "")
        if not bank_name:
            for sf in (doc.get("source_files") or []):
                bank_name = _bank_label(str(sf))
                if bank_name:
                    break
        doc_bank_by_id[doc.get("id")] = bank_name

        cs = (doc.get("analytics") or {}).get("credit_scoring_inputs") or {}
        if cs:
            credit_scoring_inputs_list.append(cs)

    inter_account_transfer = _build_inter_account_transfer(
        txns, transfer_link_rows, doc_bank_by_id, currency,
    )

    # PAR-189 Stage 8 — Account Coverage. No new fetch: acct_cov_raw is the
    # same dict already resolved above for RiskAssessment (Stage 1) and
    # coverage_incomplete (Stage 4).
    account_coverage = _build_account_coverage(acct_cov_raw, currency)

    # PAR-189 Stage 9 — 4-Point Reconciliation. No new fetch: recon_section,
    # coverage_incomplete and missing_note are all already resolved above.
    # `fy` mirrors render_snapshot_html()'s own derivation exactly.
    four_point_recon = _build_four_point_reconciliation(
        recon_section,
        recon_available,
        coverage_incomplete,
        missing_note,
        str(af_financial_year or "") if recon_available else "",
        currency,
        recon_check_config,
        # PAR-207 — gap-waterfall inputs. All three are already resolved above
        # (acct_cov_raw at the top of this function, af from the audited-
        # financials fetch, and inter_account_transfer built just above), so
        # the waterfalls add no fetch of their own.
        acct_cov_raw=acct_cov_raw,
        af=af,
        transfer_state=inter_account_transfer.state,
    )

    supplier_payments = _build_supplier_payments(txns, entity_name_by_id, supplier_config)
    tax_compliance = _build_tax_compliance(txns, in_active_period, tax_config)
    tax_payment_pattern = _build_tax_payment_pattern(txns)
    inventory = _build_inventory(af, recon_available, inventory_config)
    loans = _build_loan_activity(txns, in_active_period, af, recon_available, loans_r, coverage_incomplete)
    risk = _build_risk_assessment(
        txns, recon_tier, acct_cov_raw, transaction_patterns.critical_count, supplier_config,
    )

    # PAR-189 Stage 11 — Key Metrics. No new fetch: txns/canon_tagged/
    # in_active_period/af/recon_section/currency are all already resolved
    # above (af now widened to include turnover_cents/profit_before_tax_cents,
    # which no earlier stage needed).
    key_metrics = _build_key_metrics(
        txns, canon_tagged, in_active_period, recon_available, af, recon_section, currency,
    )

    # PAR-189 Stage 11 — Observed Patterns, the last section. No new fetch:
    # txns/canon_tagged/in_active_period are already resolved above, and
    # credit_scoring_inputs_list now comes from the same pds_documents fetch
    # Inter-Account Transfer Analysis already does (widened this stage).
    observed_patterns = _build_observed_patterns(
        txns, canon_tagged, in_active_period, credit_scoring_inputs_list,
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
        "inter_account_transfer": inter_account_transfer,
        "account_coverage": account_coverage,
        "four_point_reconciliation": four_point_recon,
        "monthly_cashflow": monthly_cashflow,
        "key_metrics": key_metrics,
        "observed_patterns": observed_patterns,
    }
