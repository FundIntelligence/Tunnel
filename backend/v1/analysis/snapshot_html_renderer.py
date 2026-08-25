"""
Snapshot HTML renderer — 3-page Jinja2 HTML snapshot from live deal data.
"""
from __future__ import annotations

import io
import json
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import qrcode
from jinja2 import Environment, FileSystemLoader
from qrcode.image.svg import SvgImage

from ..analytics import CASHFLOW_INFLOW_ROLES, monthly_cashflow as _monthly_cashflow
from ..core.snapshot_engine import decompress_canonical_json_if_needed
from .snapshot_generator import generate_reconciliation_section
from .snapshot_context import (
    AccountCoverage as _AccountCoverage,
    Composition as _Composition,
    FourPointReconciliation as _FourPointReconciliation,
    InterAccountTransfer as _InterAccountTransfer,
    Inventory as _Inventory,
    LoanActivity as _LoanActivity,
    Money as _Money,
    Percent as _Percent,
    RiskAssessment as _RiskAssessment,
    SupplierPayments as _SupplierPayments,
    TaxCompliance as _TaxCompliance,
    TaxPaymentPattern as _TaxPaymentPattern,
    TransactionPatterns as _TransactionPatterns,
    build_snapshot_context,
)
from ._snapshot_fetch_helpers import _bank_label, _get_supabase, _paginate

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000

MONTH_ABBR = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}

REVENUE_ROLES = {"revenue_operational", "mpesa_inflow", "pesalink_inflow"}

# PAR-189 Stage 7: _BANK_ALIASES / _bank_label moved to
# _snapshot_fetch_helpers.py (unchanged) so snapshot_context.py can share them
# without a circular import. _bank_label is re-imported above, so
# `renderer._bank_label(...)` still resolves for existing callers and tests.
# _BANK_ALIASES is not re-imported — nothing outside the helper module reads it.


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


def _fmt_kes_compact(cents: int) -> str:
    kes = cents / 100
    if kes >= 1_000_000:
        return f"{kes / 1_000_000:.1f}M"
    if kes >= 1_000:
        return f"{kes / 1_000:.0f}K"
    return f"{kes:,.0f}"


def _fmt_kes_millions(cents: int) -> str:
    return f"KES {cents / 100 / 1_000_000:.1f}M"


_BADGE_VARIANCE_CLASS = {"b-exact": "ok", "b-ok": "ok", "b-warn": "gap", "b-variance": "bad"}


def _status_to_badge(status: str, coverage_incomplete: bool = False):
    """
    Maps a reconciliation status to a (badge_class, badge_label) pair.
    coverage_incomplete distinguishes a gap explainable by missing bank
    statement coverage (amber b-warn) from a gap on otherwise-complete data,
    which is treated as a genuine unexplained variance (red b-variance).

    PAR-189 Stage 9: render_snapshot_html() no longer calls this — the last
    caller (4-Point Reconciliation) now consumes the shared context's
    semantic ReconStatus and maps it via _RECON_STATUS_BADGE below. This is
    deliberately KEPT rather than deleted: it is the reference oracle that
    tests_v1/test_par189_stage4_extraction.py diffs _resolve_recon_status()
    against across every status/coverage combination, and v1/tests also
    exercises it directly. Deleting it would remove a real invariant test,
    not just dead code.
    """
    if status == "EXACT_MATCH":
        return ("b-exact", "Exact match")
    if status in ("ACCEPTABLE", "ACCEPTABLE_VARIANCE", "HEALTHY"):
        return ("b-ok", "Acceptable")
    if coverage_incomplete:
        return ("b-warn", "Gap · coverage incomplete")
    return ("b-variance", "Variance")


def _make_qr_svg(url: str) -> str:
    qr = qrcode.make(url, image_factory=SvgImage)
    buf = io.BytesIO()
    qr.save(buf)
    svg = buf.getvalue().decode("utf-8")
    return svg[svg.find("<svg"):]


# ─────────────────────────────────────────────────────────────────────────────
# PAR-189 Stage 1 — WeasyPrint-side adapters
#
# build_snapshot_context() (snapshot_context.py) returns format-agnostic typed
# values (Money, Percent, enums). These two functions reproduce, byte for
# byte, the presentation dicts the Jinja template already expects for these
# two sections — this is the only place WeasyPrint-specific string formatting
# for these sections should happen going forward.
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_money_kes(money: Optional[_Money]) -> str:
    if money is None:
        return _fmt_kes(0)
    return _fmt_kes(money.cents)


def _fmt_pct_1dp(pct: _Percent) -> str:
    """
    Format a 0-1 Percent that came from an already-rounded upstream as the
    original's one-decimal string.

    PAR-189 Stage 8 (introduced) / Stage 9 (generalised — renamed from
    _fmt_coverage_pct now that four reconciliation fields use it too).
    The round(..., 2) is load-bearing, not cosmetic.

    Several upstream percentages reach this layer ALREADY rounded to
    hundredths — `calculate_account_coverage()` returns
    round(basis_points / 100, 2), and reconciliation_engine returns
    round(x / y * 100, 2) for every gap_pct / variance_pct. The original
    formatted those values directly with f"{value:.1f}". Storing them as 0-1
    fractions (ratified decision #3) and multiplying back by 100 reintroduces
    float representation error, changing the rendered digit for any value
    landing exactly on a .x5 boundary. Re-rounding to hundredths undoes that
    error and reproduces the original byte-for-byte.

    Measured, not assumed: 45 of the 10,001 possible coverage values (0-100%)
    diverge under the naive round-trip, and 748 of the 100,001 values across
    the -500%..+500% range the reconciliation variances span — negatives very
    much included, which those fields routinely are. With the re-round,
    zero divergences across both domains.

    This is NOT theoretical. Stage 1's Risk Assessment adapter shipped the
    naive form in PR #161; it escaped seven stages of byte-diffs because the
    Deed verification document has no audited financials, so every affected
    field renders "--" on both sides.

    Percentages NOT sourced from a pre-rounded upstream (supplier top-share,
    revenue concentration) are true ratios computed identically on both paths
    and correctly do not use this helper.
    """
    return f"{round(pct.value * 100, 2):.1f}"


def _supplier_payments_ctx_from(sp: _SupplierPayments) -> Dict[str, Any]:
    if not sp.available:
        return {"available": False}
    return {
        "available":    True,
        "total_str":    _fmt_money_kes(sp.total),
        "txn_count":    sp.txn_count,
        "entity_count": sp.counterparty_count,
        "top_name":     sp.top_counterparty,
        "top_pct_str":  f"{sp.top_share.value * 100:.1f}%",
        "clause":       sp.narrative,
    }


def _risk_assessment_ctx_from(risk: _RiskAssessment) -> Dict[str, Any]:
    if risk.revenue_concentration_state == "UNAVAILABLE":
        largest_rev_pct_str = "--"
    elif risk.revenue_concentration_state == "INSUFFICIENT_DATA":
        largest_rev_pct_str = f"insufficient data (N={risk.revenue_concentration_sample})"
    else:
        largest_rev_pct_str = f"{risk.largest_revenue_share.value * 100:.1f}%"

    # PAR-189 Stage 8 fix: was f"{risk.coverage.value * 100:.1f}", which
    # diverged from the pre-Stage-1 original for 45 of the 10,001 possible
    # coverage values. The original reused Account Coverage's already-formatted
    # coverage_pct string; see _fmt_pct_1dp() for why the re-round is
    # required to reproduce it.
    missing_pct = _fmt_pct_1dp(risk.coverage) if risk.coverage is not None else "--"

    return {
        "tier":                   risk.tier,
        "advisory_tier":          risk.advisory_tier if risk.advisory_tier is not None else "--",
        "missing_pct":            missing_pct,
        "largest_rev_pct_str":    largest_rev_pct_str,
        "anomaly_summary":        risk.anomaly_narrative,
        "conclusion":             risk.conclusion,
        "transfer_note":          risk.transfer_caveat,
    }


def _transaction_patterns_ctx_from(tp: _TransactionPatterns) -> Dict[str, Any]:
    return {
        "critical_count":  tp.critical_count,
        "high_count":      tp.high_count,
        "total_flagged":   tp.total_flagged,
        "total_txn_count": tp.total_txn_count,
        "clause":          tp.narrative,
    }


def _tax_compliance_ctx_from(tc: _TaxCompliance) -> Dict[str, Any]:
    return {
        "total_str":      _fmt_money_kes(tc.total),
        "n_tax_months":   tc.months_with_tax,
        "n_total_months": tc.months_total,
        "kra_compliance": tc.status,
        "clause":         tc.narrative,
    }


def _tax_payment_pattern_ctx_from(tpp: _TaxPaymentPattern) -> Dict[str, Any]:
    return {
        "tax_count":         tpp.txn_count,
        "tax_freq_str":      f"{tpp.avg_per_month:.1f} / month" if tpp.avg_per_month is not None else "--",
        "tax_penalty_count": tpp.penalty_count,
        "tax_jan_spike_str": _fmt_money_kes(tpp.jan_spike_total) if tpp.jan_spike_total is not None else "",
        "tax_total_str":     _fmt_money_kes(tpp.total),
        "tax_note":          tpp.narrative,
    }


def _inventory_ctx_from(inv: _Inventory) -> Dict[str, Any]:
    if not inv.available:
        return {
            "available": False,
            "financial_year": inv.fiscal_year or "",
            "note": inv.narrative,
        }
    return {
        "available":      True,
        "financial_year": inv.fiscal_year or "",
        "inventory_str":  _fmt_money_kes(inv.inventory),
        "cogs_str":       _fmt_money_kes(inv.cost_of_sales),
        "turnover_str":   f"{inv.turnover:.1f}x",
        "dio_str":        f"{inv.days_inventory_outstanding:.0f} days" if inv.days_inventory_outstanding is not None else "--",
        "clause":         inv.narrative,
        "confidence_str": (
            f"{inv.extraction_confidence:.2f}" if inv.extraction_confidence is not None else "not recorded"
        ),
    }


# Mirrors _status_to_badge()'s branching exactly, keyed by the already-
# resolved ReconStatus instead of a raw status string + coverage_incomplete
# bool — the resolution itself now happens in snapshot_context.py
# (_resolve_recon_status), this table is just the renderer's own
# status->style mapping, per PAR-189's "renderer owns colour/class" rule.
_RECON_STATUS_BADGE = {
    "EXACT_MATCH":  ("b-exact",    "Exact match"),
    "ACCEPTABLE":   ("b-ok",       "Acceptable"),
    "COVERAGE_GAP": ("b-warn",     "Gap · coverage incomplete"),
    "VARIANCE":     ("b-variance", "Variance"),
}


def _loan_activity_ctx_from(loans: _LoanActivity) -> Dict[str, Any]:
    loan_facilities = []
    for fac in loans.facilities:
        match_class, match_label = _RECON_STATUS_BADGE[fac.status]
        loan_facilities.append({
            "name":        fac.name,
            "amount_str":  _fmt_money_kes(fac.amount),
            "match_class": match_class,
            "match_label": match_label,
        })

    return {
        "loan_disbursed_str":    _fmt_money_kes(loans.disbursed),
        "loan_repaid_str":       _fmt_money_kes(loans.repaid),
        "loan_net_str":          _fmt_kes(abs(loans.net.cents)),
        "loan_freq_str":         f"{loans.repayments_per_month:.1f} txns / month",
        "loan_facility_count":   loans.repayment_txn_count,
        "loan_facilities":       loan_facilities,
        "loan_recon_status":     loans.status_raw or "",
        "loan_bank_net_str":     _fmt_money_kes(loans.bank_net),
        "loan_declared_net_str": _fmt_money_kes(loans.declared_net),
        "loan_variance_str":     f"{loans.variance.value * 100:.1f}%" if loans.variance is not None else "0%",
    }


def _inter_account_transfer_ctx_from(iat: _InterAccountTransfer) -> Dict[str, Any]:
    """
    PAR-189 Stage 7. WeasyPrint owns the state -> badge-label mapping; the
    shared context carries only the semantic state (ratified decision #5).
    The three labels below are the exact strings the original computed inline.
    """
    badge_label = {
        "DETECTED":           "Detected",
        "NO_TRANSFERS_FOUND": "No Transfers Found",
        "UNAVAILABLE":        "Not Available",
    }[iat.state]
    return {
        "badge_label":   badge_label,
        "pairs": [
            {"label": p.label, "count": p.count, "total_str": _fmt_money_kes(p.total)}
            for p in iat.pairs
        ],
        "note":          iat.note,
        "override_note": iat.override_note,
    }


# PAR-189 Stage 9 — WeasyPrint's style tables for the 4-Point Reconciliation
# table. The shared context carries only the semantic ReconStatus; these three
# mappings are presentation and stay here per ratified decision #5. Values are
# unchanged from the original's _status_to_badge() / _BADGE_VARIANCE_CLASS.
_RECON_STATUS_BADGE = {
    "EXACT_MATCH":  ("b-exact",    "Exact match"),
    "ACCEPTABLE":   ("b-ok",       "Acceptable"),
    "COVERAGE_GAP": ("b-warn",     "Gap · coverage incomplete"),
    "VARIANCE":     ("b-variance", "Variance"),
}
# Per-row variance formatting. The suffix and the missing-value fallback both
# differ by row in the original — Revenue/Expenses read "% gap" while Cash and
# Loan read "%", and Loan alone falls back to "0%" rather than "--". Preserved
# exactly rather than unified.
_RECON_VARIANCE_FORMAT = {
    "cash_position": ("%",     "--"),
    "revenue":       ("% gap", "--"),
    "expenses":      ("% gap", "--"),
    "loan_activity": ("%",     "0%"),
}


def _four_point_recon_ctx_from(fpr: _FourPointReconciliation) -> Dict[str, Any]:
    """
    PAR-189 Stage 9. Returns (recon_rows, recon_fiscal_note) as the template
    expects them. When unavailable, both take the original's empty defaults
    and the template renders the separate static locked-state section instead.
    """
    rows: List[Dict] = []
    for c in fpr.checks:
        badge_class, badge_label = _RECON_STATUS_BADGE[c.status]
        suffix, fallback = _RECON_VARIANCE_FORMAT[c.key]
        variance_str = (
            f"{_fmt_pct_1dp(c.variance)}{suffix}" if c.variance is not None else fallback
        )
        rows.append({
            "check":          c.label,
            "observed_str":   _fmt_money_kes(c.observed),
            "observed_sub":   c.observed_sub,
            "declared_str":   _fmt_money_kes(c.declared),
            "declared_sub":   c.declared_sub,
            "variance_str":   variance_str,
            "variance_class": _BADGE_VARIANCE_CLASS[badge_class],
            "badge_class":    badge_class,
            "badge_label":    badge_label,
            "assessment":     c.assessment,
        })
    return {
        "recon_rows": rows,
        "recon_fiscal_note": fpr.fiscal_note if fpr.fiscal_note is not None else "",
    }


# PAR-189 Stage 8 — WeasyPrint's style tables for Account Coverage. These are
# the three CSS-class lookups the original kept inline inside
# render_snapshot_html(); per ratified decision #5 they belong to the renderer,
# not the shared context, which carries only Materiality /
# AccountSubmissionStatus enums. Values are unchanged from the original.
_AC_STAT_COLOR = {  # advisory tier → coverage-stat-value modifier
    "NEGLIGIBLE": "ok", "MINOR": "warn", "MATERIAL": "warn", "CRITICAL": "critical",
}
_AC_MATERIALITY_PILL = {  # account materiality → status-pill class
    "NEGLIGIBLE": "status-matched", "MINOR": "status-matched",
    "MATERIAL": "status-critical", "CRITICAL": "status-critical",
}
_AC_SUBMISSION_PILL = {  # submission status → status-pill class
    "SUBMITTED": "status-matched", "MISSING": "status-missing",
}
_AC_SUBMISSION_LABEL = {  # submission status → displayed label (glyph is presentation)
    "SUBMITTED": "✓ Submitted", "MISSING": "Missing",
}


def _account_coverage_ctx_from(ac: _AccountCoverage) -> Dict[str, Any]:
    """
    PAR-189 Stage 8. Reproduces the presentation dict the template already
    reads. The "--"/"" fallbacks below are the original's own defaults for
    absent keys, applied here rather than in the shared context.

    `missing_count` is emitted because the original emitted it, keeping this
    dict identical to the pre-extraction one — but note the template does not
    currently read it (same category as the dead `.color` field Stage 5 found
    on the composition segments). Left in rather than quietly dropped.
    """
    if not ac.available:
        return {"available": False, "note": ac.unavailable_note or ""}

    color_class = _AC_STAT_COLOR.get(ac.advisory_tier, "critical")
    return {
        "available":            True,
        "coverage_pct":         _fmt_pct_1dp(ac.coverage),
        "coverage_color_class": color_class,
        "declared_count":       ac.declared_count,
        "submitted_count":      ac.submitted_count,
        "missing_count":        ac.missing_count,
        "missing_balance_str":  _fmt_money_kes(ac.missing_balance),
        "advisory_tier":        ac.advisory_tier if ac.advisory_tier is not None else "--",
        "recommendation":       ac.recommendation if ac.recommendation is not None else "",
        "accounts": [
            {
                "bank_name":         a.bank_name if a.bank_name is not None else "--",
                "declared_str":      _fmt_money_kes(a.declared_balance),
                "status_label":      _AC_SUBMISSION_LABEL[a.status],
                "status_class":      _AC_SUBMISSION_PILL[a.status],
                "materiality":       a.materiality if a.materiality is not None else "--",
                "materiality_class": _AC_MATERIALITY_PILL.get(a.materiality, "status-critical"),
            }
            for a in ac.accounts
        ],
    }


def _composition_ctx_from(comp: _Composition) -> Dict[str, Any]:
    # comp.segments deliberately carries no colour (design doc §1c flags
    # inflow_segments[].color / outflow_segments[].color as a hex-literal
    # format-agnostic violation) — and unlike Stage 4's badge classes, the
    # CURRENT template never actually reads seg.color at all (only .label,
    # .pct, .amount_str — confirmed by grep against snapshot.html), so there
    # is nothing here for a WeasyPrint adapter to reconstruct. Not dropped
    # silently: flagged in the PAR-189 report.
    segments = [
        {
            "label": seg.label,
            "pct": round(seg.share.value * 100),
            "amount_str": _fmt_kes_millions(seg.amount.cents),
        }
        for seg in comp.segments
    ]
    return {
        "total_str": _fmt_kes_millions(comp.total.cents),
        "segments": segments,
        "warn": comp.advisory or "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def render_snapshot_html(
    deal_id: str,
    view: str = "observed_recon",
    partner_name: Optional[str] = None,
) -> str:
    """
    view: observed_recon (default, existing 3-page flow — branches internally on
          recon_available) | verify (standalone sealed summary page).
    partner_name: when set, the page header shows the partner's name with
          "Intelligence by P/ Parity" credit instead of the plain Parity header.
          Content and figures are identical — only the header branding changes.
    """
    sb = _get_supabase()

    # PAR-189 Stage 1: Risk Assessment Summary + Supplier Payment Analysis are
    # computed by build_snapshot_context() (snapshot_context.py) instead of
    # inline below. This does its own independent fetch (deal_id only) rather
    # than sharing the fetches this function does further down — see the
    # PAR-189 report for why, and what that implies for the remaining sections.
    shared_ctx = build_snapshot_context(deal_id)

    # 1. Deal metadata
    deal = (
        sb.table("pds_deals")
        .select("company_name, currency, analyst_notes")
        .eq("id", deal_id)
        .single()
        .execute()
        .data
    ) or {}
    company_name: str = deal.get("company_name") or "--"
    currency: str     = deal.get("currency") or "KES"
    # PAR-189 Stage 3: analyst_notes now sourced from build_snapshot_context()
    # (shared_ctx["analyst_notes"]) instead of this same `deal` row read
    # directly above. The `deal` fetch itself is untouched (still needed for
    # company_name/currency), so analyst_notes is fetched twice for now —
    # same accepted duplication pattern as every other Stage 1-3 field.
    analyst_notes: str = shared_ctx["analyst_notes"] or ""

    # 2. Snapshot — decode canonical_json
    snap_res = (
        sb.table("pds_snapshots")
        .select("sha256_hash, created_at, canonical_json")
        .eq("deal_id", deal_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    snap: Dict = snap_res.data[0] if snap_res.data else {}
    sha256_hash: str = snap.get("sha256_hash") or ""
    raw_cj = snap.get("canonical_json") or ""
    canonical_str = decompress_canonical_json_if_needed(raw_cj)
    canonical: Dict = json.loads(canonical_str) if canonical_str else {}

    # 3. Documents — credit_scoring_inputs + doc pills (still doc-level ingestion
    # metadata, unrelated to the monthly-cashflow unification below).
    docs = (
        sb.table("pds_documents")
        .select("id, analytics, storage_url, source_files")
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    credit_scoring_inputs_list: List[Dict] = []
    doc_pills: List[Dict] = []
    # PAR-189 Stage 7: the document_id -> detected-bank-label map that used to
    # be built here existed solely to name each side of an Inter-Account
    # Transfer pair. That section now builds its own from its own
    # pds_documents fetch inside build_snapshot_context(), so the map is no
    # longer accumulated here — bank_name below still feeds the doc pill label.

    for doc in docs:
        analytics = doc.get("analytics") or {}
        summary   = analytics.get("summary") or {}
        txn_count = summary.get("total_transactions") or 0
        url       = doc.get("storage_url") or ""
        sf_list   = doc.get("source_files") or []

        bank_name = _bank_label(url)
        if not bank_name:
            for sf in sf_list:
                bank_name = _bank_label(str(sf))
                if bank_name:
                    break
        label = f"{bank_name or 'Bank'} · {txn_count:,} txns"
        doc_pills.append({"label": label, "active": True})

        cs = analytics.get("credit_scoring_inputs") or {}
        if cs:
            credit_scoring_inputs_list.append(cs)

    # 3b. Monthly cashflow + inflow/outflow composition — sourced from the
    # sealed canonical_json (canon_tagged below), via the exact same
    # monthly_cashflow() / CASHFLOW_INFLOW_ROLES that the live
    # /analytics/monthly-cashflow endpoint (backend/v1/analytics.py) uses for
    # the app's Analysis tab. This used to be three independent
    # implementations that could (and did) silently disagree:
    #   1. parity-ingestion/app/analytics.py::monthly_cashflow() — raw
    #      pre-classification credit/debit off the bank statement, cached once
    #      on pds_documents.analytics at ingestion time and never refreshed.
    #   2. backend/v1/analytics.py::monthly_cashflow() — role-classified,
    #      the trusted definition behind the live endpoint / app's Analysis tab.
    #   3. This file's own Composition section — a third, exclude-list based
    #      total that didn't match either of the above.
    # Both the table and the composition section below now derive from #2's
    # exact function and role set, applied to this snapshot's own sealed
    # transactions/txn_entity_map, so there is exactly one definition left.
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

    monthly_merged: Dict[str, Dict[str, int]] = {
        row["month"]: {"inflow_cents": row["inflow_cents"], "outflow_cents": row["outflow_cents"]}
        for row in _monthly_cashflow(canon_tagged)
    }

    # 4. Audited financials (optional — sets recon_available)
    af_result = (
        sb.table("pds_audited_financials")
        .select(
            "loan_breakdown, turnover_cents, profit_before_tax_cents, financial_year, "
            "inventory_cents, cost_of_sales_cents, extraction_confidence"
        )
        .eq("deal_id", deal_id)
        .execute()
        .data or []
    )
    recon_available = len(af_result) > 0
    af: Dict = af_result[0] if recon_available else {}

    # 5. Paginated transactions + roles
    txn_rows = _paginate(
        sb, "pds_raw_transactions",
        "id, txn_date, signed_amount_cents, abs_amount_cents, normalized_descriptor, balance_cents, "
        "account_id, document_id",
        deal_id,
    )
    # PAR-63: entity_id added so Supplier Payment Analysis can attribute spend
    # to a counterparty name (pds_entities), not just a role-level total.
    map_rows   = _paginate(sb, "pds_txn_entity_map", "txn_id, role, entity_id", deal_id)
    role_by_txn = {r["txn_id"]: r["role"] for r in map_rows}
    entity_id_by_txn = {r["txn_id"]: r.get("entity_id") for r in map_rows}

    # PAR-63: entity display names for the Supplier Payment Analysis section.
    # One deal-scoped, paginated fetch (same _paginate helper already used for
    # pds_raw_transactions/pds_txn_entity_map above) — not a per-row lookup.
    entity_rows = _paginate(sb, "pds_entities", "entity_id, display_name", deal_id)
    entity_name_by_id: Dict[str, str] = {
        e["entity_id"]: e.get("display_name") for e in entity_rows
    }

    txns = [{
        "txn_date": t["txn_date"],
        "signed":   t["signed_amount_cents"] or 0,
        # abs_amount_cents was NULL on every row platform-wide until the
        # ingestion fix that stopped stripping it before insert (it was
        # never actually a DB-generated column). Derive it here too, so
        # rows ingested before that fix still render correctly rather than
        # silently zeroing outflow composition and loan activity totals.
        "abs":      t["abs_amount_cents"] if t["abs_amount_cents"] is not None else abs(t["signed_amount_cents"] or 0),
        "desc":     t["normalized_descriptor"] or "",
        "balance":  t["balance_cents"],
        "role":     role_by_txn.get(t["id"], "other"),
        "entity_id": entity_id_by_txn.get(t["id"]),
    } for t in txn_rows]

    # 6. Reconciliation engine (only when audited financials present).
    #    Prefer the reconciliation section SEALED into the snapshot's canonical_json so
    #    the PDF renders the hashed values rather than a live recompute that can drift
    #    from the snapshot. Legacy snapshots written before recon_section was sealed fall
    #    back to a live recompute.
    recon_section: Dict = {}
    if recon_available:
        sealed_recon = canonical.get("recon_section")
        recon_section = sealed_recon if sealed_recon else generate_reconciliation_section(deal_id)

    # PAR-189 Stage 9: the local acct_cov_raw derivation that used to sit here
    # is gone. It fed only Account Coverage (extracted in Stage 8) and the
    # 4-Point Reconciliation badge softening (extracted in this stage), and
    # build_snapshot_context() resolves the same value from the same
    # recon_section. recon_section itself is still needed locally below.

    # ── Active period ──────────────────────────────────────────────────────
    # Drives every "this period" filter below (avg revenue, loan frequency,
    # cashflow rows/notes). When an audited financial year is declared, scope
    # to that calendar year. Otherwise there's no real "year" to scope to —
    # bank-statement-only deals commonly submit a 12-13 month trailing
    # lookback that crosses a calendar year boundary (e.g. Jan 2025-Jan
    # 2026), so filtering by max(txn_years) would keep only the trailing
    # partial year and silently drop every other month. Include every month
    # present instead.
    if recon_available and af.get("financial_year"):
        active_year = str(af["financial_year"])
        _in_active_period = lambda m: m.startswith(f"{active_year}-")
    else:
        active_year = ""
        _in_active_period = lambda m: True

    # ── Computed metrics ──────────────────────────────────────────────────────

    # Avg monthly revenue
    by_month_rev: Dict[str, int] = defaultdict(int)
    for t in txns:
        if t["signed"] > 0 and t["role"] in REVENUE_ROLES:
            m = (t["txn_date"] or "")[:7]
            if _in_active_period(m):
                by_month_rev[m] += t["signed"]
    avg_rev_cents = (
        int(sum(by_month_rev.values()) / len(by_month_rev)) if by_month_rev else 0
    )

    # Inflow composition — CASHFLOW_INFLOW_ROLES include-list, the same
    # definition monthly_merged above and the live endpoint use (see the
    # "Monthly cashflow" comment above for why this used to be a third,
    # independent, exclude-list-based total that didn't match either).
    by_role_in: Dict[str, int] = defaultdict(int)
    total_in = 0
    for t in canon_tagged:
        if t["amount_cents"] > 0 and t["role"] in CASHFLOW_INFLOW_ROLES:
            by_role_in[t["role"]] += t["amount_cents"]
            total_in += t["amount_cents"]

    # Outflow composition — every negative transaction counts, no role
    # exclusions, matching the live endpoint's definition exactly.
    by_role_out: Dict[str, int] = defaultdict(int)
    total_out = 0
    for t in canon_tagged:
        if t["amount_cents"] < 0:
            amt = abs(t["amount_cents"])
            by_role_out[t["role"]] += amt
            total_out += amt

    # Income quality
    op_in = sum(v for k, v in by_role_in.items() if k in REVENUE_ROLES)
    income_quality_pct = (op_in / total_in * 100) if total_in else 0

    # Loan repayment frequency (active year)
    repay_months: Dict[str, int] = defaultdict(int)
    for t in txns:
        if t["role"] == "loan_repayment" and t["signed"] < 0:
            m = (t["txn_date"] or "")[:7]
            if _in_active_period(m):
                repay_months[m] += 1
    loan_freq = (
        sum(repay_months.values()) / len(repay_months) if repay_months else 0
    )
    loan_repayment_txn_count = sum(1 for t in txns if t["role"] == "loan_repayment" and t["signed"] < 0)

    # PAR-189 Stage 4: loan_disbursed_cents/loan_repaid_cents/loan_net_cents
    # used to be computed here — now sourced from build_snapshot_context()
    # (shared_ctx["loans"]) via _loan_activity_ctx_from(). loan_freq /
    # loan_repayment_txn_count stay computed below (unchanged) because Key
    # Metrics (not yet extracted) still reads them directly.

    # Cash trend (null-safe — balance_cents may be null for pre-migration rows)
    bal_txns = sorted(
        [t for t in txns if t["balance"] is not None],
        key=lambda x: x["txn_date"] or "",
    )
    if bal_txns:
        first_bal = bal_txns[0]["balance"]
        last_bal  = bal_txns[-1]["balance"]
        yoy_pct   = ((last_bal - first_bal) / abs(first_bal) * 100) if first_bal else None
        cash_trend_str = f"{yoy_pct:+.1f}%" if yoy_pct is not None else "--"
        cash_trend_sub = f"{currency} {first_bal/100:,.0f} → {last_bal/100:,.0f} YoY"
    else:
        cash_trend_str = "--"
        cash_trend_sub = "balance data unavailable"

    # Needs-review count
    needs_review_count = sum(1 for t in txns if t["role"] == "needs_review")

    # Tax Payment Pattern (PAR-189 Stage 6: computation now lives in
    # build_snapshot_context() — see _tax_payment_pattern_ctx_from() above).

    # Cashflow net-negative months
    period_months = sorted(m for m in monthly_merged if _in_active_period(m))
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

    # ── Monthly Cashflow Pattern (PAR-63) ─────────────────────────────────────
    # Peak/trough + trend summary over the same monthly_merged/period_months
    # already used above for cashflow_note/neg_months — single source
    # (canonical_json via canon_tagged), confirmed self-consistent (no
    # numerator/denominator split across sources, unlike the bug fixed in
    # Tax Compliance Analysis). No new computation beyond what this file
    # already tracks; this is a one-time summary sentence, not a new series.
    if len(period_months) < 2:
        cashflow_trend_note = "Only one month of data is available — a trend cannot yet be established." if period_months else ""
        cashflow_peak_trough_note = ""
    else:
        nets_by_month = {
            m: monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"]
            for m in period_months
        }
        trough_month = min(nets_by_month, key=lambda m: nets_by_month[m])
        peak_month   = max(nets_by_month, key=lambda m: nets_by_month[m])
        first_net = nets_by_month[period_months[0]]
        last_net  = nets_by_month[period_months[-1]]
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

    # ── Period label ────────────────────────────────────────────────────────
    fy = str(af.get("financial_year") or "") if recon_available else ""
    if fy:
        period_label = f"FY{fy} · Jan 1 – Dec 31 {fy}"
    elif txns:
        dates = sorted(t["txn_date"] for t in txns if t["txn_date"])
        period_label = f"FY{dates[-1][:4]} · {dates[0]} – {dates[-1]}"
    else:
        period_label = "--"

    # ── Report ID + QR ──────────────────────────────────────────────────────
    report_id = (
        f"PR-{sha256_hash[:8].upper()}" if sha256_hash
        else f"PR-{uuid.uuid4().hex[:8].upper()}"
    )
    verify_url = f"https://paritytunnel.com/verify/{report_id}"
    qr_svg     = _make_qr_svg(verify_url)
    generated_date = datetime.utcnow().strftime("%B %-d, %Y")

    # ── Tier badge ───────────────────────────────────────────────────────────
    # New design system defines only two tier badge colours: tier-high (green,
    # for MEDIUM/HIGH_CONFIDENCE) and tier-low (amber, for LOW_CONFIDENCE and
    # the no-audited-financials observed state).
    if recon_available:
        recon_tier = recon_section.get("tier") or "LOW_CONFIDENCE"
        tier_badge_class = "tier-high" if recon_tier in ("HIGH_CONFIDENCE", "MEDIUM_CONFIDENCE") else "tier-low"
        tier_badge_text  = f"● {recon_tier} · reconciled"
    else:
        recon_tier       = "OBSERVED"
        tier_badge_class = "tier-low"
        tier_badge_text  = "● Observed · bank data only"

    # ── Data source pills ────────────────────────────────────────────────────
    data_source_pills = list(doc_pills)
    if recon_available:
        fy_label = f"Audited financials · FY{fy}" if fy else "Audited financials"
        data_source_pills.append({"label": fy_label, "active": True})
        data_source_note = (
            "Bank statements + audited financials reconciled · "
            "4-point reconciliation complete"
        )
    else:
        data_source_pills.append({"label": "Audited financials · not submitted", "active": False})
        data_source_note = (
            "Report covers bank-observed data only · "
            "Submit audited financials to unlock reconciliation"
        )
    data_source_pills.append({"label": "CRB · not submitted", "active": False})
    data_source_pills.append({"label": "Identity · not submitted", "active": False})

    total_txn_count = len(txns)

    # ── Key metrics (4 cells, different per state) ───────────────────────────
    if recon_available:
        turnover_cents = int(af.get("turnover_cents") or 0)
        pbt_cents      = int(af.get("profit_before_tax_cents") or 0)
        pbt_margin     = (pbt_cents / turnover_cents * 100) if turnover_cents > 0 else 0

        loans_r = recon_section.get("loan_activity") or {}
        loan_var_pct = loans_r.get("variance_pct")
        loan_var_str = (
            f"{abs(loan_var_pct):.1f}% var" if loan_var_pct is not None else "0% var"
        )

        rev_r    = recon_section.get("revenue") or {}
        rev_gap  = rev_r.get("gap_pct")
        rev_gap_str = f"{rev_gap:.1f}%" if rev_gap is not None else "--"

        kms = [
            {
                "label": "Avg monthly revenue",
                "value": _fmt_kes_compact(avg_rev_cents),
                "sub":   f"{currency} · operational inflows",
                "color_class": "",
            },
            {
                "label": "PBT margin",
                "value": f"{pbt_margin:.2f}%",
                "sub":   f"vs declared turnover · FY{fy}",
                "color_class": "positive" if pbt_margin > 0 else "negative",
            },
            {
                "label": "Loan reconciliation",
                "value": loan_var_str,
                "sub":   f"{loans_r.get('status', '')} · Note 14",
                "color_class": "warning",
            },
            {
                "label": "Revenue gap",
                "value": rev_gap_str,
                "sub":   "observed vs declared · accrual basis",
                "color_class": "warning" if (rev_gap or 0) > 15 else "",
            },
        ]
    else:
        kms = [
            {
                "label": "Avg monthly revenue",
                "value": _fmt_kes_compact(avg_rev_cents),
                "sub":   f"{currency} · operational inflows",
                "color_class": "",
            },
            {
                "label": "Income quality",
                "value": f"{income_quality_pct:.1f}%",
                "sub":   "operational vs total inflows",
                "color_class": "positive" if income_quality_pct >= 70 else "warning",
            },
            {
                "label": "Loan obligations",
                "value": f"{loan_freq:.1f}/mo",
                "sub":   f"repayments · {loan_repayment_txn_count} txns detected",
                "color_class": "warning",
            },
            {
                "label": "Cash trend",
                "value": cash_trend_str,
                "sub":   cash_trend_sub,
                "color_class": "positive" if cash_trend_str.startswith("+") else "warning",
            },
        ]

    # ── Monthly cashflow chart rows ──────────────────────────────────────────
    active_months = period_months
    max_abs_net = (
        max(abs(monthly_merged[m]["inflow_cents"] - monthly_merged[m]["outflow_cents"])
            for m in active_months)
        if active_months else 1
    ) or 1

    cashflow_rows_ctx = []
    for m in active_months:
        v = monthly_merged[m]
        net     = v["inflow_cents"] - v["outflow_cents"]
        abs_net = abs(net)
        bar_pct = min(int(abs_net / max_abs_net * 100), 100)
        sign    = "+" if net >= 0 else "−"
        cashflow_rows_ctx.append({
            "month_label":    MONTH_ABBR.get(m[5:7], m[5:7]),
            "inflow_str":     f"{v['inflow_cents'] / 100:,.0f}",
            "outflow_str":    f"{v['outflow_cents'] / 100:,.0f}",
            "net_str":        f"{sign}{abs_net / 100:,.0f}",
            "net_color_class": "pos" if net >= 0 else "neg",
            "positive":       net >= 0,
            "bar_pct":        bar_pct,
        })

    # ── Composition segments ─────────────────────────────────────────────────
    # PAR-189 Stage 5: computation now lives in build_snapshot_context() — see
    # _composition_ctx_from() above. by_role_in/total_in/by_role_out/total_out
    # (computed above, unchanged) stay needed locally: Key Metrics'
    # income_quality_pct (not yet extracted) already used them before this
    # block even ran. mpesa_cents/mpesa_pct specifically are recomputed as a
    # small residual below because the not-yet-extracted Observed Patterns
    # "M-Pesa concentration" card still reads mpesa_pct directly.
    inflow_composition_ctx = _composition_ctx_from(shared_ctx["inflow"])
    outflow_composition_ctx = _composition_ctx_from(shared_ctx["outflow"])
    inflow_segments = inflow_composition_ctx["segments"]
    outflow_segments = outflow_composition_ctx["segments"]
    inflow_warn = inflow_composition_ctx["warn"]
    outflow_warn = outflow_composition_ctx["warn"]

    mpesa_cents = by_role_in.get("mpesa_inflow", 0)
    mpesa_pct   = (mpesa_cents / total_in * 100) if total_in else 0

    # ── Supplier Payment Analysis (PAR-63) ────────────────────────────────────
    # PAR-189 Stage 1: computation now lives in build_snapshot_context()
    # (snapshot_context.py) — this just re-derives the presentation dict the
    # template expects from that typed result. See _supplier_payments_ctx_from()
    # above.
    supplier_payments_ctx: Dict[str, Any] = _supplier_payments_ctx_from(shared_ctx["supplier_payments"])

    # ── Transaction Pattern Analysis (PAR-63) ─────────────────────────────────
    # PAR-189 Stage 2: computation now lives in build_snapshot_context()
    # (snapshot_context.py) — this just re-derives the presentation dict the
    # template expects. See _transaction_patterns_ctx_from() above.
    transaction_patterns_ctx: Dict[str, Any] = _transaction_patterns_ctx_from(
        shared_ctx["transaction_patterns"]
    )

    # ── Tax Compliance Analysis (PAR-63) ──────────────────────────────────────
    # PAR-189 Stage 2: the tax-specific part of this computation now lives in
    # build_snapshot_context() — see _tax_compliance_ctx_from() above. What
    # stays here is a reduced version of the original single-pass loop, kept
    # ONLY for payroll_stability_live / n_payroll_months / n_total_months,
    # which the not-yet-extracted "Irregular payroll" Observed Pattern card
    # below still reads. The original loop also accumulated tax_months_active
    # / tax_total_cents_active / tax_txn_count_active in the same pass — that
    # part moved into build_snapshot_context()'s _build_tax_compliance() and
    # is intentionally NOT recomputed here.
    tax_compliance_ctx: Dict[str, Any] = _tax_compliance_ctx_from(shared_ctx["tax_compliance"])

    all_months_active: set = set()
    payroll_months_active: set = set()
    for t in txns:
        m = (t["txn_date"] or "")[:7]
        if t["txn_date"] and _in_active_period(m):
            all_months_active.add(m)
            if t["role"] == "payroll":
                payroll_months_active.add(m)

    n_total_months = len(all_months_active)
    n_payroll_months = len(payroll_months_active)

    # Mirrors backend/v1/analytics.py::credit_scoring_inputs()'s own
    # payroll_stability thresholds (consistent/mostly-consistent/irregular
    # cutoffs) — same classification, recomputed live over this render's
    # txns/active-period instead of read from the stale cached blob.
    if n_total_months == 0 or n_payroll_months == 0:
        payroll_stability_live = "NOT_DETECTED"
    elif n_payroll_months == n_total_months:
        payroll_stability_live = "CONSISTENT"
    elif n_payroll_months >= n_total_months * 8 // 10:
        payroll_stability_live = "MOSTLY_CONSISTENT"
    else:
        payroll_stability_live = "IRREGULAR"

    # ── Inter-Account Transfer Analysis — PAR-189 Stage 7 ────────────────────
    # Now computed by build_snapshot_context() (shared_ctx["inter_account_transfer"])
    # rather than inline here. The three-way branch (real pds_transfer_links
    # rows / genuine zero / pre-PAR-102 tagging-gap stub) and both narratives
    # moved unchanged into _build_inter_account_transfer(); only the badge
    # string stayed on this side, in _inter_account_transfer_ctx_from(), since
    # it is presentation. See that builder's docstring for the two fidelity
    # points preserved (DETECTED is gated on transfer_links alone, and the
    # analyst-override count is independent of system detection).
    inter_account_transfer_ctx: Dict[str, Any] = _inter_account_transfer_ctx_from(
        shared_ctx["inter_account_transfer"]
    )

    # ── Tax Payment Pattern — PAR-189 Stage 6 (shared_ctx["tax_payment_pattern"])
    tax_payment_pattern_ctx: Dict[str, Any] = _tax_payment_pattern_ctx_from(
        shared_ctx["tax_payment_pattern"]
    )

    # ── Pattern cards ─────────────────────────────────────────────────────────
    _TAG_CLASS  = {"Watch": "t-wat", "Observed": "t-chk", "Pattern": "t-pat", "Coverage": "t-chk"}
    _ITEM_CLASS = {"Watch": "watch", "Observed": "check", "Pattern": "pattern", "Coverage": "check"}

    patterns: List[Dict] = []

    if mpesa_pct > 40:
        tag = "Watch"
        patterns.append({
            "name": "M-Pesa concentration",
            "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"M-Pesa inflows represent {mpesa_pct:.1f}% of total observed inflows",
            "check_prompt": "→ Review: consistent with declared customer mix and B2B model?",
        })

    for cs in credit_scoring_inputs_list:
        if cs.get("kra_compliance") == "GAPS_DETECTED":
            tag = "Observed"
            patterns.append({
                "name": "Tax payment gap",
                "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
                "data_statement": cs.get("kra_note") or "Tax payment gaps detected",
                "check_prompt": "→ Review: gap months explained by filing schedule or missed payments?",
            })
            break

    # PAR-100: payroll_stability_live/n_payroll_months/n_total_months are all
    # computed above from the single live pass over txns (same block as Tax
    # Compliance Analysis) — no cached credit_scoring_inputs field used here.
    if payroll_stability_live == "IRREGULAR":
        tag = "Pattern"
        patterns.append({
            "name": "Irregular payroll",
            "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"Payroll detected in {n_payroll_months} of {n_total_months} months",
            "check_prompt": "→ Review: casual workforce or payroll routed off-statement?",
        })

    if len(neg_months) > 2:
        label_months = ", ".join(
            MONTH_ABBR.get(m[5:7], m[5:7]) for m in neg_months[:3]
        ) + ("..." if len(neg_months) > 3 else "")
        tag = "Pattern"
        patterns.append({
            "name": "Net-negative months",
            "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"{len(neg_months)} of {len(period_months)} months net-negative: {label_months}",
            "check_prompt": "→ Review: seasonal pattern or sustained cash drain?",
        })

    if needs_review_count > 100:
        tag = "Coverage"
        patterns.append({
            "name": "Analyst classification pending",
            "tag": tag, "tag_class": _TAG_CLASS[tag], "item_class": _ITEM_CLASS[tag],
            "data_statement": f"{needs_review_count} transactions flagged needs_review",
            "check_prompt": "→ Review: resolve in Parity dashboard before finalising snapshot.",
        })

    patterns = patterns[:5]

    # ── 4-Point Reconciliation — PAR-189 Stage 9 ─────────────────────────────
    # Now computed by build_snapshot_context()
    # (shared_ctx["four_point_reconciliation"]) rather than inline here. All
    # four rows, their per-row status derivations and their assessment prose
    # moved into _build_four_point_reconciliation(); only the badge/variance
    # CSS classes and the per-row variance formatting stayed on this side, in
    # _four_point_recon_ctx_from(), since they are presentation.
    #
    # This also retires the renderer's own missing_bank_names /
    # coverage_incomplete / missing_note derivation: 4-Point Reconciliation
    # was its last consumer, and build_snapshot_context() has computed the
    # same values since Stage 1. See that builder's docstring for the four
    # fidelity points preserved (notably: cash position is deliberately NOT
    # coverage-softened, and each row derives its status differently).
    _recon_ctx = _four_point_recon_ctx_from(shared_ctx["four_point_reconciliation"])
    recon_rows: List[Dict] = _recon_ctx["recon_rows"]
    recon_fiscal_note: str = _recon_ctx["recon_fiscal_note"]

    # ── Loan facilities table (recon state) + Loan Activity Detected ─────────
    # PAR-189 Stage 4: both now come from build_snapshot_context()'s single
    # LoanActivity (shared_ctx["loans"]) — see _loan_activity_ctx_from() above.
    # (The note that used to sit here about coverage_incomplete still being
    # needed locally for 4-Point Reconciliation is obsolete as of Stage 9 —
    # that section is extracted and the local derivation is gone.)
    loan_ctx: Dict[str, Any] = _loan_activity_ctx_from(shared_ctx["loans"])

    # ── Inventory Analysis (PAR-63, recon state only) ────────────────────────
    # PAR-189 Stage 3: computation now lives in build_snapshot_context() — see
    # _inventory_ctx_from() above. This just re-derives the presentation dict
    # the template expects.
    inventory_ctx: Dict[str, Any] = _inventory_ctx_from(shared_ctx["inventory"])

    # ── Verify-page summary (reuses figures already computed above) ──────────
    if recon_available:
        loan_recon_label = (shared_ctx["loans"].status_raw or "VARIANCE").replace("_", " ").title()
    else:
        loan_recon_label = "Not reconciled"
    vp_confidence_color = "positive" if recon_tier == "HIGH_CONFIDENCE" else (
        "warning" if recon_tier in ("MEDIUM_CONFIDENCE", "LOW_CONFIDENCE") else ""
    )

    # ── Account Coverage — PAR-189 Stage 8 ───────────────────────────────────
    # Now computed by build_snapshot_context() (shared_ctx["account_coverage"])
    # rather than inline here. The available/unavailable branch, the per-account
    # rows and the locked-state prose all moved into _build_account_coverage();
    # the three CSS-class lookup tables and the "✓ Submitted" label stayed on
    # this side, in _account_coverage_ctx_from(), since they are presentation.
    account_coverage_ctx: Dict[str, Any] = _account_coverage_ctx_from(
        shared_ctx["account_coverage"]
    )

    # ── Risk Assessment Summary (PAR-63) ──────────────────────────────────────
    # PAR-189 Stage 1: computation now lives in build_snapshot_context()
    # (snapshot_context.py), including the two PAR-188 disclosures
    # (conclusion / transfer_note below) as non-optional fields — this just
    # re-derives the presentation dict the template expects. See
    # _risk_assessment_ctx_from() above.
    risk_assessment_ctx: Dict[str, Any] = _risk_assessment_ctx_from(shared_ctx["risk"])

    # ── Render template ───────────────────────────────────────────────────────
    templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(os.path.abspath(templates_dir)))
    template = env.get_template("snapshot.html")

    context: Dict[str, Any] = {
        "view":               view,
        "partner_name":       partner_name,
        "company_name":       company_name,
        "sector":             "--",
        "period_label":       period_label,
        "generated_date":     generated_date,
        "analyst_notes":      analyst_notes,
        "report_id":          report_id,
        "sha256_hash":        sha256_hash,
        "qr_svg":             qr_svg,
        "verify_url":         verify_url,
        "currency":           currency,
        "recon_available":    recon_available,
        "recon_tier":         recon_tier,
        "vp_confidence_color": vp_confidence_color,
        "loan_recon_label":   loan_recon_label,
        "tier_badge_class":   tier_badge_class,
        "tier_badge_text":    tier_badge_text,
        "data_source_pills":  data_source_pills,
        "data_source_note":   data_source_note,
        "total_txn_count":    total_txn_count,
        "kms":                kms,
        "cashflow_rows":      cashflow_rows_ctx,
        "cashflow_note":      cashflow_note,
        "cashflow_peak_trough_note": cashflow_peak_trough_note,
        "cashflow_trend_note": cashflow_trend_note,
        "inflow_total_str":   inflow_composition_ctx["total_str"],
        "inflow_segments":    inflow_segments,
        "inflow_warn":        inflow_warn,
        "outflow_total_str":  outflow_composition_ctx["total_str"],
        "outflow_segments":   outflow_segments,
        "outflow_warn":       outflow_warn,
        "tax_count":          tax_payment_pattern_ctx["tax_count"],
        "tax_freq_str":       tax_payment_pattern_ctx["tax_freq_str"],
        "tax_penalty_count":  tax_payment_pattern_ctx["tax_penalty_count"],
        "tax_jan_spike_str":  tax_payment_pattern_ctx["tax_jan_spike_str"],
        "tax_total_str":      tax_payment_pattern_ctx["tax_total_str"],
        "tax_note":           tax_payment_pattern_ctx["tax_note"],
        "loan_disbursed_str": loan_ctx["loan_disbursed_str"],
        "loan_repaid_str":    loan_ctx["loan_repaid_str"],
        "loan_net_str":       loan_ctx["loan_net_str"],
        "loan_freq_str":      loan_ctx["loan_freq_str"],
        "loan_facility_count": loan_ctx["loan_facility_count"],
        "loan_facilities":    loan_ctx["loan_facilities"],
        "loan_recon_status":  loan_ctx["loan_recon_status"],
        "loan_bank_net_str":  loan_ctx["loan_bank_net_str"],
        "loan_declared_net_str": loan_ctx["loan_declared_net_str"],
        "loan_variance_str":  loan_ctx["loan_variance_str"],
        "recon_rows":         recon_rows,
        "recon_fiscal_note":  recon_fiscal_note,
        "patterns":           patterns,
        "account_coverage":   account_coverage_ctx,
        "inventory":          inventory_ctx,
        "supplier_payments":  supplier_payments_ctx,
        "tax_compliance":     tax_compliance_ctx,
        "transaction_patterns": transaction_patterns_ctx,
        "inter_account_transfer": inter_account_transfer_ctx,
        "risk_assessment":    risk_assessment_ctx,
    }

    return template.render(**context)
