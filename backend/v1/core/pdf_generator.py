"""
Parity snapshot PDF — reportlab implementation.

Ports generate-parity-pdf.ts layout to Python.
Input:  decompressed canonical_json dict.
Output: PDF bytes (A4, Courier throughout, no external assets).

Sections:
  01  Credit Scoring Inputs
  02  Deal Summary
  03  Financial Metrics
  04  Reconciliation Summary
  05  Entity Breakdown
  06  Concentration
  07  Monthly Entity Breakdown
  08  Items Requiring Review
  09  Monthly Cashflow & Cash Flow Habits
  10  Overrides
  11  Snapshot Provenance
      Footer (page N / total on every page)
"""
from __future__ import annotations

import io
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = A4
MARGIN = 48.0          # points
BODY_W = PAGE_W - 2 * MARGIN

_FONT = "Courier"
_FONT_BOLD = "Courier-Bold"

# ---------------------------------------------------------------------------
# Paragraph styles  (unique names avoid reportlab style-cache warnings)
# ---------------------------------------------------------------------------

_S_TITLE = ParagraphStyle("parity_title", fontName=_FONT_BOLD, fontSize=13, leading=18, textColor=colors.black)
_S_HEAD  = ParagraphStyle("parity_head",  fontName=_FONT_BOLD, fontSize=9,  leading=14, textColor=colors.black)
_S_BODY  = ParagraphStyle("parity_body",  fontName=_FONT,      fontSize=8,  leading=12, textColor=colors.black)
_S_SMALL = ParagraphStyle("parity_small", fontName=_FONT,      fontSize=7,  leading=11, textColor=colors.black)

# ---------------------------------------------------------------------------
# Role sets (mirrors generate-parity-pdf.ts and classifier.py)
# ---------------------------------------------------------------------------

_REVENUE_ROLES  = frozenset({"revenue_operational", "revenue_non_operational"})
_SUPPLIER_ROLES = frozenset({"supplier_payment"})
_PAYROLL_ROLES  = frozenset({"payroll"})
_LOAN_ROLES     = frozenset({"loan_repayment", "loan_inflow"})
_TAX_ROLES      = frozenset({"tax_payment", "kra_payment"})
_REVIEW_ROLES   = frozenset({"needs_review", "capital_injection", "loan_inflow"})

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_cents(cents: int, currency: str) -> str:
    return f"{currency} {cents / 100:,.2f}"


def _fmt_bp(bp: int) -> str:
    return f"{bp / 100:.2f}%"


def _fmt_mom(bps: Optional[int]) -> str:
    if bps is None:
        return "—"
    prefix = "+" if bps >= 0 else ""
    return f"{prefix}{bps / 100:.1f}%"


def _trunc(s: str, n: int) -> str:
    return s[:n - 1] + "…" if len(s) > n else s


# ---------------------------------------------------------------------------
# Platypus helpers
# ---------------------------------------------------------------------------

def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def _section_header(text: str) -> List:
    return [Spacer(1, 8), _p(text, _S_HEAD), Spacer(1, 4)]


def _body_line(text: str) -> Paragraph:
    return _p(text, _S_BODY)


def _table(
    data: List[List[str]],
    col_widths: List[float],
    right_cols: Optional[List[int]] = None,
) -> Table:
    """Build a grid Table with Courier font, bold header row."""
    cmds = [
        ("FONTNAME",      (0, 0), (-1, -1), _FONT),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("TEXTCOLOR",     (0, 0), (-1, -1), colors.black),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.black),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("FONTNAME",      (0, 0), (-1, 0),  _FONT_BOLD),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, colors.black),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]
    for col in (right_cols or []):
        cmds.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(cmds))
    return t


# ---------------------------------------------------------------------------
# Derived-data computation
# ---------------------------------------------------------------------------

def _build_txn_role_map(canonical: Dict[str, Any]) -> Dict[str, str]:
    """UUID (pds_raw_transactions.id) → role string.

    After export, txn_entity_map.txn_id is rewritten to the row UUID.
    Transaction objects carry both id (UUID) and txn_id (sha256 hash).
    Keying by UUID lets _role_for_txn() match via t["id"].
    """
    return {
        str(m.get("txn_id") or ""): (m.get("role") or "")
        for m in canonical.get("txn_entity_map", [])
    }


def _role_for_txn(txn_role_map: Dict[str, str], t: Dict[str, Any]) -> str:
    """Return the classified role for a transaction dict.

    Tries t["id"] (UUID — matches post-export map keys) first, then
    t["txn_id"] (sha256 — fallback for in-memory / test data).
    """
    return (
        txn_role_map.get(str(t.get("id") or ""))
        or txn_role_map.get(str(t.get("txn_id") or ""))
        or ""
    )


def _compute_entity_breakdown(canonical: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Aggregate txn_entity_map by entity_id → entity_name, role, total_abs_cents, pct_of_total, txn_count."""
    entities_by_id = {str(e["entity_id"]): e for e in canonical.get("entities", [])}

    # Amount lookup: try both UUID 'id' and sha256 'txn_id' keys
    txn_amount: Dict[str, int] = {}
    for t in canonical.get("transactions", []):
        amt = int(t.get("signed_amount_cents", 0))
        for key in ("id", "txn_id"):
            tid = str(t.get(key) or "")
            if tid:
                txn_amount[tid] = amt

    agg: Dict[str, Dict[str, Any]] = {}
    for m in canonical.get("txn_entity_map", []):
        eid = str(m.get("entity_id") or "")
        if not eid:
            continue
        tid = str(m.get("txn_id") or "")
        amt = txn_amount.get(tid, 0)
        if eid not in agg:
            ent = entities_by_id.get(eid, {})
            agg[eid] = {
                "entity_id": eid,
                "entity_name": ent.get("display_name") or (_trunc(eid, 16)),
                "role": m.get("role") or "unknown",
                "total_abs_cents": 0,
                "txn_count": 0,
            }
        agg[eid]["total_abs_cents"] += abs(amt)
        agg[eid]["txn_count"] += 1

    rows = list(agg.values())
    total = sum(r["total_abs_cents"] for r in rows)
    for r in rows:
        r["pct_of_total"] = (r["total_abs_cents"] / total * 100) if total > 0 else 0.0
    rows.sort(key=lambda r: r["total_abs_cents"], reverse=True)
    return rows


def _compute_monthly_cashflow(canonical: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Group transactions by YYYY-MM; compute inflow / outflow / net / MoM change."""
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"inflow": 0, "outflow": 0})
    for t in canonical.get("transactions", []):
        ds = str(t.get("txn_date") or "")
        if len(ds) < 7:
            continue
        month = ds[:7]
        amt = int(t.get("signed_amount_cents", 0))
        if amt > 0:
            buckets[month]["inflow"] += amt
        else:
            buckets[month]["outflow"] += abs(amt)

    rows: List[Dict[str, Any]] = []
    prev_net: Optional[int] = None
    for month in sorted(buckets):
        inflow  = buckets[month]["inflow"]
        outflow = buckets[month]["outflow"]
        net     = inflow - outflow
        if prev_net is None or prev_net == 0:
            mom_bps, mom_reliable = None, False
        else:
            mom_bps      = int((net - prev_net) / abs(prev_net) * 10_000)
            mom_reliable = True
        rows.append({
            "month":        month,
            "inflow_cents": inflow,
            "outflow_cents": outflow,
            "net_cents":    net,
            "mom_change_bps": mom_bps,
            "mom_reliable":   mom_reliable,
        })
        prev_net = net
    return rows


def _compute_credit_scoring_inputs(
    canonical: Dict[str, Any],
    monthly: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute credit scoring metrics from transactions + monthly cashflow."""
    transactions = canonical.get("transactions", [])
    txn_role = _build_txn_role_map(canonical)

    months_with_inflow = [m for m in monthly if m["inflow_cents"] > 0]
    inflows   = [m["inflow_cents"]  for m in months_with_inflow]
    nets      = [m["net_cents"]     for m in monthly]
    out_list  = [m["outflow_cents"] for m in monthly]

    avg_inflow    = int(sum(inflows)  / len(inflows))   if inflows  else 0
    median_inflow = int(statistics.median(inflows))      if inflows  else 0
    avg_outflow   = int(sum(out_list) / len(out_list))   if out_list else 0
    avg_net       = int(sum(nets)     / len(nets))       if nets     else 0
    peak_net      = max(nets, default=0)
    trough_net    = min(nets, default=0)

    # Revenue growth: first vs last month with inflow
    if len(months_with_inflow) >= 2:
        first_in = months_with_inflow[0]["inflow_cents"]
        last_in  = months_with_inflow[-1]["inflow_cents"]
        rev_growth_bps = int((last_in - first_in) / first_in * 10_000) if first_in > 0 else 0
    else:
        rev_growth_bps = 0

    # Loan repayment burden: numerator = loan_repayment outflows only
    # denominator = all outflows (signed_amount_cents < 0)
    total_out = sum(
        abs(int(t.get("signed_amount_cents", 0)))
        for t in transactions
        if int(t.get("signed_amount_cents", 0)) < 0
    )
    loan_out = sum(
        abs(int(t.get("signed_amount_cents", 0)))
        for t in transactions
        if _role_for_txn(txn_role, t) == "loan_repayment"
        and int(t.get("signed_amount_cents", 0)) < 0
    )
    loan_burden_bps = int(loan_out / total_out * 10_000) if total_out > 0 else 0

    # Payroll months detected
    payroll_months = {
        str(t.get("txn_date") or "")[:7]
        for t in transactions
        if _role_for_txn(txn_role, t) in _PAYROLL_ROLES
        and len(str(t.get("txn_date") or "")) >= 7
    }
    n_payroll = len(payroll_months)
    n_months  = len(monthly)
    if n_payroll == 0:
        payroll_stability = "NOT_DETECTED"
    elif n_payroll >= n_months * 0.9:
        payroll_stability = "CONSISTENT"
    elif n_payroll >= n_months * 0.5:
        payroll_stability = "IRREGULAR"
    else:
        payroll_stability = "SPARSE"

    # KRA / tax compliance
    tax_months: set = set()
    tax_total = 0
    for t in transactions:
        if _role_for_txn(txn_role, t) in _TAX_ROLES:
            ds = str(t.get("txn_date") or "")
            if len(ds) >= 7:
                tax_months.add(ds[:7])
            tax_total += abs(int(t.get("signed_amount_cents", 0)))
    n_tax = len(tax_months)
    if n_tax >= n_months * 0.8:
        kra_compliance, kra_note = "COMPLIANT", f"Tax payments in {n_tax}/{n_months} months"
    elif n_tax > 0:
        kra_compliance, kra_note = "PARTIAL",   f"Tax payments in {n_tax}/{n_months} months"
    else:
        kra_compliance, kra_note = "NOT_DETECTED", "No KRA/tax payments detected"

    return {
        "average_monthly_inflow_cents":  avg_inflow,
        "median_monthly_inflow_cents":   median_inflow,
        "average_monthly_outflow_cents": avg_outflow,
        "average_net_monthly_cents":     avg_net,
        "peak_net_position_cents":       peak_net,
        "trough_net_position_cents":     trough_net,
        "revenue_growth_bps":            rev_growth_bps,
        "loan_repayment_burden_bps":     loan_burden_bps,
        "payroll_stability":             payroll_stability,
        "payroll_months_detected":       n_payroll,
        "kra_compliance":                kra_compliance,
        "kra_note":                      kra_note,
        "tax_total_cents":               tax_total,
        "statement_months":              n_months,
        "month_count_with_inflow":       len(months_with_inflow),
    }


def _compute_monthly_entity_breakdown(canonical: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-month revenue / suppliers / payroll / loan-repayment / tax buckets."""
    txn_role = _build_txn_role_map(canonical)
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {
        "revenue_in_cents": 0, "suppliers_cents": 0,
        "payroll_cents": 0, "loan_repayment_cents": 0, "tax_cents": 0,
    })
    for t in canonical.get("transactions", []):
        ds = str(t.get("txn_date") or "")
        if len(ds) < 7:
            continue
        month = ds[:7]
        amt  = int(t.get("signed_amount_cents", 0))
        role = _role_for_txn(txn_role, t)
        if   role in _REVENUE_ROLES  and amt > 0: buckets[month]["revenue_in_cents"]    += amt
        elif role in _SUPPLIER_ROLES and amt < 0: buckets[month]["suppliers_cents"]      += abs(amt)
        elif role in _PAYROLL_ROLES  and amt < 0: buckets[month]["payroll_cents"]         += abs(amt)
        elif role in _LOAN_ROLES     and amt < 0: buckets[month]["loan_repayment_cents"]  += abs(amt)
        elif role in _TAX_ROLES      and amt < 0: buckets[month]["tax_cents"]             += abs(amt)
    return [{"month": m, **buckets[m]} for m in sorted(buckets)]


# ---------------------------------------------------------------------------
# Numbered canvas — supplies "N / total" footer on every page
# ---------------------------------------------------------------------------

class _NumberedCanvas(Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states: List[dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            Canvas.showPage(self)
        Canvas.save(self)

    def _draw_footer(self, total: int) -> None:
        w = self._pagesize[0]
        self.saveState()
        self.setLineWidth(0.5)
        self.line(MARGIN, 28, w - MARGIN, 28)
        self.setFont(_FONT, 6)
        self.drawString(
            MARGIN, 16,
            "This record reflects the committed Parity snapshot as written to the database. Pipeline: v1.",
        )
        self.drawRightString(w - MARGIN, 16, f"{self._pageNumber} / {total}")
        self.restoreState()


# ---------------------------------------------------------------------------
# FX conversion helpers
# ---------------------------------------------------------------------------

_FX_CURRENCY_CODES = frozenset({"EUR", "USD", "GBP", "CHF", "JPY", "CNY", "AED", "ZAR"})
_FX_CONVERSION_KEYWORDS = frozenset({"CONVERSION TRANSFER", "FX CONVERSION", "CURRENCY CONVERSION", "CONVERSION"})


def _is_fx_conversion_desc(desc: str) -> bool:
    d = desc.upper()
    has_kw = any(kw in d for kw in _FX_CONVERSION_KEYWORDS)
    has_cc = any(cc in d for cc in _FX_CURRENCY_CODES)
    if has_kw and has_cc:
        return True
    if has_cc and ("TO KSH" in d or "TO KES" in d):
        return True
    import re
    if has_cc and re.search(r'AT\s+\d+\.?\d*', d) and ("TRF FROM" in d or "TRANSFER FROM" in d):
        return True
    return False


def _compute_fx_metrics(canonical: Dict[str, Any]) -> Dict[str, Any]:
    """Compute FX conversion metrics from canonical JSON."""
    txn_role = _build_txn_role_map(canonical)
    transactions = canonical.get("transactions", [])

    fx_txns = [
        t for t in transactions
        if _role_for_txn(txn_role, t) == "currency_conversion"
        or _is_fx_conversion_desc(str(t.get("description") or t.get("normalized_descriptor") or ""))
    ]

    if not fx_txns:
        return {"count": 0}

    total_fx = sum(abs(int(t.get("signed_amount_cents", 0))) for t in fx_txns)
    largest  = max(abs(int(t.get("signed_amount_cents", 0))) for t in fx_txns)
    months   = sorted({
        str(t.get("txn_date") or "")[:7]
        for t in fx_txns
        if len(str(t.get("txn_date") or "")) >= 7
    })
    total_in = sum(int(t.get("signed_amount_cents", 0)) for t in transactions if int(t.get("signed_amount_cents", 0)) > 0)
    fx_pct   = (total_fx / total_in * 100) if total_in > 0 else 0.0

    return {
        "count":       len(fx_txns),
        "total_cents": total_fx,
        "largest_cents": largest,
        "months":      months,
        "pct_of_inflow": fx_pct,
    }


def _add_fx_section(story: List[Any], fx: Dict[str, Any], currency: str) -> None:
    """Append FX conversion section to story. No-op if no conversions."""
    if not fx.get("count"):
        return
    story += _section_header("FX  FOREIGN EXCHANGE CONVERSIONS")
    fx_rows = [
        ["Metric", "Value", "Note"],
        ["Total Converted",
         _fmt_cents(fx["total_cents"], currency),
         f"{fx['count']} transactions"],
        ["Largest Conversion",
         _fmt_cents(fx["largest_cents"], currency),
         "Single transaction"],
        ["As % of Inflow",
         f"{fx['pct_of_inflow']:.1f}%",
         "Of total credit inflow"],
        ["Active Months",
         ", ".join(fx["months"]) if fx["months"] else "—",
         f"{len(fx['months'])} months"],
    ]
    story.append(_table(fx_rows, [140, 120, BODY_W - 260], right_cols=[1]))
    story.append(Spacer(1, 4))
    story.append(_p(
        "<b>Note:</b> Currency conversions are excluded from operational revenue "
        "calculations. Verify that conversion source represents export proceeds "
        "or legitimate foreign currency inflows.",
        _S_SMALL,
    ))
    story.append(Spacer(1, 12))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _add_enrichment_sections(
    story: List[Any],
    enrichment: Dict[str, Any],
    currency: str,
) -> None:
    """Append Section B: Analyst Enrichment pages to story."""
    from reportlab.platypus import PageBreak

    story.append(PageBreak())
    story.append(_p("SECTION B — ANALYST ENRICHMENT", _S_TITLE))
    story.append(Spacer(1, 4))
    story.append(_p(
        "This section records analyst-added context layered on top of the deterministic base snapshot. "
        "The base snapshot (Section A) is immutable and was not modified.",
        _S_SMALL,
    ))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black, spaceAfter=8))

    # B1 — Enrichment provenance
    story += _section_header("B1  ENRICHMENT PROVENANCE")
    for label, value in [
        ("enrichment_id:",    enrichment.get("id") or "—"),
        ("enriched_hash:",    enrichment.get("enriched_hash") or "—"),
        ("base_snapshot_id:", enrichment.get("base_snapshot_id") or "—"),
        ("analyst:",          enrichment.get("analyst_name") or enrichment.get("analyst_id") or "—"),
        ("created:",          str(enrichment.get("created_at") or "—")[:19]),
        ("status:",           "FINAL" if enrichment.get("is_final") else "DRAFT"),
    ]:
        story.append(_p(f"<b>{label}</b> {value}", _S_SMALL))
        story.append(Spacer(1, 2))
    if enrichment.get("enrichment_reason"):
        story.append(Spacer(1, 4))
        story.append(_body_line(f"Reason: {enrichment['enrichment_reason']}"))
    story.append(Spacer(1, 8))

    # B2 — Classification overrides
    overrides = enrichment.get("overrides") or []
    story += _section_header(f"B2  CLASSIFICATION OVERRIDES ({len(overrides)})")
    if not overrides:
        story.append(_body_line("None."))
    else:
        ov_rows = [["Transaction ID", "Original Role", "Override Role", "Reason"]]
        for ov in overrides:
            txn_id = str(ov.get("txn_id") or "")
            ov_rows.append([
                _trunc(txn_id, 20),
                ov.get("original_role") or "—",
                ov.get("override_role") or "—",
                _trunc(ov.get("override_reason") or "—", 40),
            ])
        story.append(_table(ov_rows, [110, 100, 100, BODY_W - 310], right_cols=[]))
    story.append(Spacer(1, 8))

    # B3 — Custom flags
    flags = enrichment.get("flags") or []
    story += _section_header(f"B3  CUSTOM THRESHOLD ALERTS ({len(flags)})")
    if not flags:
        story.append(_body_line("None defined."))
    else:
        fl_rows = [["Flag", "Severity", "Metric / Threshold", "Result"]]
        for f in flags:
            criteria = f.get("criteria") or {}
            threshold_str = f"{criteria.get('threshold_cents', 0) / 100:,.0f} {currency}"
            cmp_map = {
                "less_than": "<", "less_than_or_equal": "≤",
                "greater_than": ">", "greater_than_or_equal": "≥",
            }
            cmp_sym = cmp_map.get(criteria.get("comparison", ""), criteria.get("comparison", ""))
            metric_str = f"{criteria.get('metric', '?')} {cmp_sym} {threshold_str}"
            triggered = f.get("triggered", False)
            count = f.get("trigger_count", 0)
            result_str = f"TRIGGERED ({count}×)" if triggered else "OK"
            fl_rows.append([
                _trunc(f.get("flag_description") or f.get("flag_name") or "—", 30),
                (f.get("flag_severity") or "—").upper(),
                metric_str,
                result_str,
            ])
        story.append(_table(fl_rows, [130, 60, 160, BODY_W - 350], right_cols=[]))

        # Detail rows for triggered flags
        triggered_flags = [f for f in flags if f.get("triggered")]
        if triggered_flags:
            story.append(Spacer(1, 6))
            story.append(_body_line("Triggered flag details:"))
            for f in triggered_flags:
                story.append(Spacer(1, 4))
                story.append(_body_line(f"  {f.get('flag_name')} — {f.get('trigger_count', 0)} breach(es):"))
                details = f.get("trigger_details") or []
                for d in details[:10]:
                    month_or_date = d.get("month") or d.get("date") or "?"
                    bal = d.get("balance_cents") or d.get("amount_cents")
                    val_str = (_fmt_cents(bal, currency) if bal is not None else "")
                    story.append(_body_line(f"    {month_or_date}  {val_str}"))
                if len(details) > 10:
                    story.append(_p(f"    … and {len(details) - 10} more", _S_SMALL))
    story.append(Spacer(1, 8))

    # B4 — Analyst narrative
    narrative = (enrichment.get("narrative") or "").strip()
    story += _section_header("B4  ANALYST NARRATIVE")
    if narrative:
        for para in narrative.split("\n\n"):
            story.append(_body_line(para.strip()))
            story.append(Spacer(1, 4))
    else:
        story.append(_body_line("No narrative provided."))
    story.append(Spacer(1, 8))


def generate_pdf(
    canonical: Dict[str, Any],
    snapshot_meta: Optional[Dict[str, Any]] = None,
    enrichment: Optional[Dict[str, Any]] = None,
    account_coverage: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    """
    Generate Parity snapshot PDF.

    canonical        — output of json.loads(decompress_canonical_json_if_needed(stored_cj))
    snapshot_meta    — optional dict with id / sha256_hash / financial_state_hash from snapshot row
    account_coverage — optional list of pds_account_coverage rows for this deal

    Returns raw PDF bytes.
    """
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 24,   # room for footer
        title="Parity Snapshot",
        author="Parity v1",
    )

    # ── Derived data ──────────────────────────────────────────────────────────
    entity_breakdown  = _compute_entity_breakdown(canonical)
    monthly_cashflow  = _compute_monthly_cashflow(canonical)
    csi               = _compute_credit_scoring_inputs(canonical, monthly_cashflow)
    monthly_entity    = _compute_monthly_entity_breakdown(canonical)
    fx_metrics        = _compute_fx_metrics(canonical)

    currency  = canonical.get("currency", "KES")
    deal_id   = canonical.get("deal_id", "—")
    tx_count  = len(canonical.get("transactions", []))
    overrides = canonical.get("overrides_applied", [])
    metrics   = canonical.get("metrics", {})
    conf      = canonical.get("confidence", {})
    rec_sum   = canonical.get("reconciliation_summary", {})
    snap      = snapshot_meta or {}

    top_suppliers = [r for r in entity_breakdown if r["role"] in _SUPPLIER_ROLES][:5]
    top_revenue   = [r for r in entity_breakdown if r["role"] in _REVENUE_ROLES][:5]
    review_ents   = [r for r in entity_breakdown if r["role"] in _REVIEW_ROLES]

    total_outflow  = sum(m["outflow_cents"] for m in monthly_cashflow)
    txn_role_map   = _build_txn_role_map(canonical)
    payroll_total  = sum(
        abs(int(t.get("signed_amount_cents", 0)))
        for t in canonical.get("transactions", [])
        if _role_for_txn(txn_role_map, t) in _PAYROLL_ROLES
        and int(t.get("signed_amount_cents", 0)) < 0
    )
    largest_rev_pct = max((r["pct_of_total"] for r in top_revenue), default=0.0)

    date_str      = datetime.utcnow().strftime("%Y-%m-%d")
    sha_raw       = snap.get("sha256_hash") or ""
    sha_truncated = (sha_raw[:16] + "…") if sha_raw else "(no hash)"

    story: List[Any] = []

    # ── 00  HEADER ────────────────────────────────────────────────────────────
    story.append(_p("PRODUCED BY PARITY", _S_TITLE))
    story.append(Spacer(1, 4))
    story.append(_p(f"Generated: {date_str}    Snapshot: {sha_truncated}", _S_SMALL))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.black, spaceAfter=8))

    # ── 01  CREDIT SCORING INPUTS ─────────────────────────────────────────────
    story += _section_header("01  CREDIT SCORING INPUTS")
    csi_rows = [
        ["Scoring Metric", "Value", "Basis"],
        ["Average Monthly Inflow",
         _fmt_cents(csi["average_monthly_inflow_cents"], currency),
         f"{csi['month_count_with_inflow']}-month arithmetic mean"],
        ["Median Monthly Inflow",
         _fmt_cents(csi["median_monthly_inflow_cents"], currency),
         f"{csi['month_count_with_inflow']}-month median"],
        ["Average Monthly Outflow",
         _fmt_cents(csi["average_monthly_outflow_cents"], currency),
         "All months arithmetic mean"],
        ["Average Net Monthly Position",
         _fmt_cents(csi["average_net_monthly_cents"], currency),
         "Inflow minus outflow mean"],
        ["Peak Net Position",
         _fmt_cents(csi["peak_net_position_cents"], currency),
         "Best single month"],
        ["Trough Net Position",
         _fmt_cents(csi["trough_net_position_cents"], currency),
         "Worst single month"],
        ["Revenue Growth",
         ("+" if csi["revenue_growth_bps"] >= 0 else "") + f"{csi['revenue_growth_bps'] / 100:.1f}%",
         "First vs last month with inflow"],
        ["Loan Repayment Burden",
         f"{csi['loan_repayment_burden_bps'] / 100:.1f}%",
         "% of total outflows"],
        ["Payroll Stability",
         csi["payroll_stability"],
         f"{csi['payroll_months_detected']} months detected"],
        ["KRA Compliance",
         csi["kra_compliance"],
         csi["kra_note"]],
    ]
    story.append(_table(csi_rows, [160, 120, BODY_W - 280], right_cols=[1]))
    story.append(Spacer(1, 16))

    # ── 02  DEAL SUMMARY ──────────────────────────────────────────────────────
    story += _section_header("02  DEAL SUMMARY")
    story.append(_body_line(f"Deal ID:                {deal_id}"))
    story.append(_body_line(f"Currency:               {currency}"))
    story.append(_body_line(f"Transactions:           {tx_count if tx_count > 0 else '—'}"))
    story.append(Spacer(1, 8))

    # ── 03  FINANCIAL METRICS ─────────────────────────────────────────────────
    story += _section_header("03  FINANCIAL METRICS")
    tier        = conf.get("tier") or "—"
    tier_capped = bool(conf.get("tier_capped"))
    tier_str    = tier + (" (capped to Medium — recon not run)" if tier_capped else "")
    story.append(_body_line(f"Coverage:               {_fmt_bp(metrics.get('coverage_bp') or 0)}"))
    story.append(_body_line(f"Confidence:             {_fmt_bp(conf.get('final_confidence_bp') or 0)}"))
    story.append(_body_line(f"Tier:                   {tier_str}"))
    story.append(_body_line(f"Reconciliation:         {metrics.get('reconciliation_status') or '—'}"))
    story.append(_body_line(f"Missing months:         {metrics.get('missing_month_count') or 0}"))
    story.append(_body_line(f"Override count:         {len(overrides)}"))
    story.append(Spacer(1, 8))

    # ── 04  RECONCILIATION SUMMARY ────────────────────────────────────────────
    if rec_sum:
        story += _section_header("04  RECONCILIATION SUMMARY")
        story.append(_body_line(f"Status:                 {rec_sum.get('status') or '—'}"))
        story.append(_body_line(f"Detected Revenue:       {_fmt_cents(rec_sum.get('detected_revenue') or 0, currency)}"))
        story.append(_body_line(f"Declared Revenue:       {_fmt_cents(rec_sum.get('declared_revenue') or 0, currency)}"))
        if rec_sum.get("delta_pct") is not None:
            story.append(_body_line(f"Delta:                  {rec_sum['delta_pct']}%"))
        if rec_sum.get("recommendation"):
            story.append(_body_line(f"Recommendation:         {rec_sum['recommendation']}"))
        story.append(Spacer(1, 8))

    # ── 05  ENTITY BREAKDOWN ──────────────────────────────────────────────────
    _EB_CAP = 50
    story += _section_header("05  ENTITY BREAKDOWN")
    if entity_breakdown:
        eb_rows = [["Entity", "Role", "Amount", "% Total", "Txns"]]
        for r in entity_breakdown[:_EB_CAP]:
            eb_rows.append([
                _trunc(r["entity_name"], 28),
                r["role"],
                _fmt_cents(r["total_abs_cents"], currency),
                f"{r['pct_of_total']:.1f}%",
                str(r["txn_count"]),
            ])
        story.append(_table(eb_rows, [130, 110, 100, 56, 40], right_cols=[2, 3, 4]))
        story.append(Spacer(1, 4))
        if len(entity_breakdown) > _EB_CAP:
            story.append(_p(
                f"Showing top {_EB_CAP} entities by transaction volume. "
                "Full entity list available in CSV export.",
                _S_SMALL,
            ))
        story.append(Spacer(1, 12))
    else:
        story.append(_body_line("No entity breakdown available."))
        story.append(Spacer(1, 4))

    # ── 06  CONCENTRATION ─────────────────────────────────────────────────────
    story += _section_header("06  CONCENTRATION")
    if top_suppliers:
        story.append(_body_line("Top suppliers by expense %:"))
        for i, r in enumerate(top_suppliers, 1):
            label = _trunc(r["entity_name"], 30)
            story.append(_body_line(f"  {i}. {label:<32} {r['pct_of_total']:.1f}%"))
    if top_revenue:
        story.append(Spacer(1, 4))
        story.append(_body_line("Top revenue entities:"))
        for i, r in enumerate(top_revenue, 1):
            label = _trunc(r["entity_name"], 30)
            story.append(_body_line(f"  {i}. {label:<32} {_fmt_cents(r['total_abs_cents'], currency)}"))
    payroll_pct = (payroll_total / total_outflow * 100) if total_outflow > 0 else 0.0
    story.append(Spacer(1, 4))
    story.append(_body_line(f"Payroll % of total outflow:     {payroll_pct:.1f}%"))
    story.append(_body_line(f"Largest revenue entity %:       {largest_rev_pct:.1f}%"))
    story.append(Spacer(1, 8))

    # ── FX  FOREIGN EXCHANGE CONVERSIONS (conditional) ───────────────────────
    _add_fx_section(story, fx_metrics, currency)

    # ── 07  MONTHLY ENTITY BREAKDOWN ──────────────────────────────────────────
    # Aggregates by role bucket per month (one row per month, not per entity).
    # Cap to top 20 months by total volume to bound length on multi-year deals.
    _MEB_CAP = 20
    if monthly_entity:
        story += _section_header("07  MONTHLY ENTITY BREAKDOWN")
        meb_display = monthly_entity[:_MEB_CAP]
        meb_rows = [["Month", "Revenue In", "Suppliers", "Payroll", "Loan Repmt", "Tax"]]
        for row in meb_display:
            meb_rows.append([
                row["month"],
                _fmt_cents(row["revenue_in_cents"], currency),
                _fmt_cents(row["suppliers_cents"], currency),
                _fmt_cents(row["payroll_cents"], currency)         if row["payroll_cents"]        > 0 else "—",
                _fmt_cents(row["loan_repayment_cents"], currency)  if row["loan_repayment_cents"] > 0 else "—",
                _fmt_cents(row["tax_cents"], currency)             if row["tax_cents"]            > 0 else "—",
            ])
        story.append(_table(meb_rows, [55, 95, 95, 82, 86, 86], right_cols=[1, 2, 3, 4, 5]))
        story.append(Spacer(1, 4))
        if len(monthly_entity) > _MEB_CAP:
            story.append(_p(
                f"Showing first {_MEB_CAP} months. Full breakdown available in CSV export.",
                _S_SMALL,
            ))
        story.append(Spacer(1, 12))

    # ── 08  ITEMS REQUIRING REVIEW ────────────────────────────────────────────
    _REV_CAP = 100
    if review_ents:
        story += _section_header("08  ITEMS REQUIRING REVIEW")
        total_review_ents = len(review_ents)
        shown = min(total_review_ents, _REV_CAP)
        if total_review_ents > _REV_CAP:
            header_line = (
                f"{total_review_ents} entities flagged for analyst review "
                f"(showing top {_REV_CAP} by amount) before finalising this record."
            )
        else:
            header_line = (
                f"{total_review_ents} "
                f"{'entity' if total_review_ents == 1 else 'entities'} flagged for analyst review "
                "before finalising this record."
            )
        story.append(_body_line(header_line))
        story.append(Spacer(1, 4))
        rev_rows = [["Entity", "Flagged As", "Amount", "Action Required"]]
        for r in review_ents[:_REV_CAP]:
            if r["role"] == "loan_inflow":
                action = "VERIFY — possible loan disbursement"
            elif r["role"] == "capital_injection":
                action = "VERIFY — possible capital injection"
            else:
                action = "CLASSIFY — large or unidentified inflow/outflow"
            rev_rows.append([
                _trunc(r["entity_name"], 32),
                r["role"],
                _fmt_cents(r["total_abs_cents"], currency),
                action,
            ])
        story.append(_table(rev_rows, [140, 90, 95, 175], right_cols=[2]))
        story.append(Spacer(1, 4))
        if total_review_ents > _REV_CAP:
            story.append(_p(
                f"Showing {_REV_CAP} of {total_review_ents} flagged entities. "
                "Full list available in CSV export.",
                _S_SMALL,
            ))
        story.append(Spacer(1, 12))

    # ── 09  MONTHLY CASHFLOW ──────────────────────────────────────────────────
    if monthly_cashflow:
        story += _section_header("09  MONTHLY CASHFLOW & CASH FLOW HABITS")
        cf_rows = [["Month", "Inflow", "Outflow", "Net Position", "MoM Change"]]
        for i, m in enumerate(monthly_cashflow):
            if i == 0:
                mom_str = "—"
            elif not m["mom_reliable"]:
                mom_str = _fmt_mom(m["mom_change_bps"]) + ("*" if m["mom_change_bps"] is not None else "")
            else:
                mom_str = _fmt_mom(m["mom_change_bps"])
            cf_rows.append([
                m["month"],
                _fmt_cents(m["inflow_cents"],  currency),
                _fmt_cents(m["outflow_cents"], currency),
                _fmt_cents(m["net_cents"],     currency),
                mom_str,
            ])
        story.append(_table(cf_rows, [55, 110, 110, 110, 110], right_cols=[1, 2, 3, 4]))
        story.append(Spacer(1, 12))

    # ── 10  OVERRIDES ─────────────────────────────────────────────────────────
    story += _section_header(f"10  OVERRIDES ({len(overrides)})")
    if not overrides:
        story.append(_body_line("None applied."))
    else:
        ents_by_id = {str(e.get("entity_id")): e for e in canonical.get("entities", [])}
        for ov in overrides:
            eid  = str(ov.get("entity_id") or "")
            ent  = ents_by_id.get(eid, {})
            name = _trunc(ent.get("display_name") or (eid[:12] + "…"), 24)
            line = (
                f"  {name:<26} {str(ov.get('old_value') or '?'):<22}"
                f" → {ov.get('new_value') or ''}   weight: {ov.get('weight', '')}"
            )
            if ov.get("reason"):
                line += f"   ({ov['reason']})"
            story.append(_body_line(line[:95]))
    story.append(Spacer(1, 8))

    # ── 11  SNAPSHOT PROVENANCE ───────────────────────────────────────────────
    story += _section_header("11  SNAPSHOT PROVENANCE")
    for label, value in [
        ("snapshot_id:",           snap.get("id") or "—"),
        ("sha256_hash:",           snap.get("sha256_hash") or "—"),
        ("financial_state_hash:",  snap.get("financial_state_hash") or "—"),
    ]:
        story.append(_p(f"<b>{label}</b> {value}", _S_SMALL))
        story.append(Spacer(1, 3))
    story.append(Spacer(1, 12))

    # ── 12  ACCOUNT COVERAGE (conditional) ────────────────────────────────────
    if account_coverage:
        story += _section_header(f"12  ACCOUNT COVERAGE ({len(account_coverage)})")
        ac_rows = [["Bank", "Declared Balance", "Status", "Materiality"]]
        for a in account_coverage:
            ac_rows.append([
                _trunc(a.get("declared_bank_name") or "—", 32),
                _fmt_cents(a.get("declared_balance_cents") or 0, currency),
                "SUBMITTED" if a.get("is_submitted") else "MISSING",
                a.get("materiality_tier") or "—",
            ])
        story.append(_table(ac_rows, [180, 120, 90, 90], right_cols=[1]))
        story.append(Spacer(1, 12))

    # ── SECTION B  ANALYST ENRICHMENT (optional) ──────────────────────────────
    if enrichment:
        _add_enrichment_sections(story, enrichment, currency)

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
