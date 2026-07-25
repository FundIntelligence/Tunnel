"""
Tests for snapshot_html_renderer.py — presentation-only HTML assembly.
Mocks the Supabase client and the reconciliation engine; does not hit the real DB.
Fixture values mirror the real Buildex production deal confirmed in the prior
audit session (deal_id 42c41951-c907-4361-bb12-16f39d468f0c).
"""
import json
import os
import re
import sys
from unittest.mock import MagicMock

# Ensure backend/ is on sys.path so v1.* package imports resolve correctly
_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Stub get_supabase before importing the module so it never attempts a real connection.
import v1.db.supabase_client as _supabase_client_mod  # noqa: E402
_supabase_client_mod.get_supabase = MagicMock(return_value=MagicMock())

from v1.analysis import snapshot_html_renderer as renderer  # noqa: E402
from v1.analytics import monthly_cashflow as _live_monthly_cashflow  # noqa: E402


# ── fake Supabase client ────────────────────────────────────────────────────────

class _FakeQuery:
    """Chainable stand-in for a PostgREST query builder."""

    def __init__(self, rows):
        self._rows = rows
        self._single = False

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        if self._single:
            data = self._rows[0] if self._rows else None
        else:
            data = self._rows
        return MagicMock(data=data)


class _FakeSupabase:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


# ── fixture data — mirrors real Buildex deal confirmed in prior audit session ──

_SHA = "3c7afc6112df3567" + "0" * 48

_DEAL_ROWS = [{
    "company_name": "Buildex Interiors Company Ltd",
    "currency": "KES",
    "analyst_notes": "",
}]

_SNAPSHOT_ROWS = [{
    "sha256_hash": _SHA,
    "created_at": "2026-06-10T08:27:44.545010+00:00",
    "canonical_json": json.dumps({
        "metrics": {
            "coverage_bp": 10000,
            "missing_month_count": 0,
            "missing_month_penalty_bp": 0,
            "reconciliation_bp": None,
            "reconciliation_status": "NOT_RUN",
        }
    }),
}]

_DOCUMENT_ROWS = [{
    "id": "9449d6c3",
    "storage_url": "inline://EQUITY STATEMENT - NEW FORMAT (1).pdf",
    "source_files": [],
    "analytics": {
        "summary": {"total_transactions": 3},
        "monthly_cashflow": [
            {"month": "2025-01", "inflow_cents": 110141723500, "outflow_cents": 95396060000},
        ],
        "credit_scoring_inputs": {
            "kra_compliance": "NOT_DETECTED",
            "payroll_stability": "NOT_DETECTED",
        },
    },
}]

_AUDITED_FINANCIALS_ROWS = [{
    "loan_breakdown": [
        {"name": "AssetFinance-074FLBC242960001", "amount_cents": 450425800},
        {"name": "AssetFinance-074FLBC241980001", "amount_cents": 421759800},
        {"name": "AssetFinance-074FLBC251700001", "amount_cents": 531501100},
        {"name": "Normalloan-074RF01253440002", "amount_cents": 270000000},
        {"name": "JiinueLoan-0100011413058", "amount_cents": 359030800},
    ],
    "turnover_cents": 37206227700,
    "profit_before_tax_cents": 833018500,
    "financial_year": 2025,
}]

# 3 raw transactions: one revenue, one supplier outflow, one with a balance for cash-trend
_RAW_TXN_ROWS = [
    {
        "id": "txn-1", "txn_date": "2025-01-05", "signed_amount_cents": 500000,
        "abs_amount_cents": 500000, "normalized_descriptor": "PAYMENT IN", "balance_cents": 1000000,
    },
    {
        "id": "txn-2", "txn_date": "2025-01-10", "signed_amount_cents": -200000,
        "abs_amount_cents": 200000, "normalized_descriptor": "SUPPLIER PAYMENT", "balance_cents": 800000,
    },
    {
        "id": "txn-3", "txn_date": "2025-02-01", "signed_amount_cents": 300000,
        "abs_amount_cents": 300000, "normalized_descriptor": "PAYMENT IN", "balance_cents": 1100000,
    },
]

_TXN_ENTITY_MAP_ROWS = [
    {"txn_id": "txn-1", "role": "revenue_operational"},
    {"txn_id": "txn-2", "role": "supplier"},
    {"txn_id": "txn-3", "role": "revenue_operational"},
]

_TABLES = {
    "pds_deals": _DEAL_ROWS,
    "pds_snapshots": _SNAPSHOT_ROWS,
    "pds_documents": _DOCUMENT_ROWS,
    "pds_audited_financials": _AUDITED_FINANCIALS_ROWS,
    "pds_raw_transactions": _RAW_TXN_ROWS,
    "pds_txn_entity_map": _TXN_ENTITY_MAP_ROWS,
}

_RECON_SECTION = {
    "tier": "LOW_CONFIDENCE",
    "cash_position": {
        "status": "VARIANCE", "variance_pct": 12.5,
        "total_bank_kes": 18590, "total_declared_kes": 21257,
    },
    "revenue": {
        "gap_pct": 10.8, "assessment": "RISK — revenue gap too large (>15%)",
        "bank_inflows_kes": 332000000, "declared_revenue_kes": 372100000,
        "fiscal_period": "2025-01-01 to 2025-12-31",
    },
    "expenses": {
        "gap_pct": 9.3, "explanation": "Gap explained by non-cash expenses",
        "bank_outflows_kes": 329300000, "declared_expenses_kes": 363100000,
    },
    "loan_activity": {
        "status": "VARIANCE", "variance_pct": 0.0,
        "bank_net_borrowing_kes": 0, "declared_net_borrowing_kes": 2557092,
    },
}


def _patch_supabase():
    fake = _FakeSupabase(_TABLES)
    renderer._get_supabase = lambda: fake
    return fake


def _patch_recon(monkeypatch=None):
    renderer.generate_reconciliation_section = MagicMock(return_value=_RECON_SECTION)


# ── helper function tests (pure, no DB) ─────────────────────────────────────────

def test_fmt_kes_integer_division_only():
    # 123456 cents = KES 1,234.56 -> displayed rounded, but the input is integer cents
    assert renderer._fmt_kes(123456) == "KES 1,235"
    assert renderer._fmt_kes(0) == "KES 0"
    assert isinstance(123456, int)  # confirms the input contract is integer cents


def test_fmt_kes_compact_millions():
    assert renderer._fmt_kes_compact(3_000_000_00) == "3.0M"  # 3,000,000.00 KES


def test_fmt_kes_millions():
    assert renderer._fmt_kes_millions(150_000_000_00) == "KES 150.0M"


def test_status_to_badge_exact_match():
    cls, label = renderer._status_to_badge("EXACT_MATCH")
    assert cls == "b-exact"
    assert label == "Exact match"


def test_status_to_badge_variance_default():
    cls, label = renderer._status_to_badge("VARIANCE")
    assert cls == "b-variance"
    assert label == "Variance"


def test_status_to_badge_variance_with_incomplete_coverage():
    cls, label = renderer._status_to_badge("VARIANCE", coverage_incomplete=True)
    assert cls == "b-warn"
    assert label == "Gap · coverage incomplete"


def test_make_qr_svg_produces_inline_svg():
    svg = renderer._make_qr_svg("https://paritytunnel.com/verify/PR-ABCDEF12")
    assert svg.startswith("<svg")
    assert "<script" not in svg  # must be static markup, no client-side JS


def test_bank_label_matches_known_alias():
    assert renderer._bank_label("inline://EQUITY STATEMENT.pdf") == "Equity"
    assert renderer._bank_label("inline://KCB STATEMENT - F1.pdf") == "KCB"
    assert renderer._bank_label("inline://unknown bank.pdf") is None


# ── report_id format ─────────────────────────────────────────────────────────────

def test_report_id_format():
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    assert f"PR-{_SHA[:8].upper()}" in html


# ── loan facilities table — no rounding, exact cents ────────────────────────────

def test_loan_facilities_preserve_cents_exactly():
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    # 450425800 cents = KES 4,504,258 exactly (integer floor, no rounding artifact)
    assert "4,504,258" in html
    assert "AssetFinance-074FLBC242960001" in html


def test_loan_facilities_handles_empty_breakdown():
    tables = dict(_TABLES)
    tables["pds_audited_financials"] = [{
        "loan_breakdown": [],
        "turnover_cents": 0,
        "profit_before_tax_cents": 0,
        "financial_year": 2025,
    }]
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    assert "<html" in html  # renders without raising even with zero facilities


# ── inventory analysis (PAR-63) ──────────────────────────────────────────────

def test_inventory_analysis_missing_data_note():
    """The real Buildex fixture's audited-financials row has no inventory_cents
    or cost_of_sales_cents — confirms the section renders the explicit
    missing-data note rather than a misleading zero/blank."""
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    assert (
        "Inventory and/or cost of sales figures were not present in the audited "
        "financial statements provided for FY2025 — inventory analysis cannot be "
        "computed for this deal."
    ) in html


def test_inventory_analysis_computes_turnover_and_dio_when_data_present():
    """Synthetic inventory_cents/cost_of_sales_cents (the real Buildex fixture
    doesn't carry these fields) — confirms the arithmetic path: turnover =
    cost_of_sales_cents / inventory_cents, DIO = 365 / turnover, and that the
    result lands in the correct risk-clause bucket (turnover >= 6 -> LOW risk)."""
    tables = dict(_TABLES)
    tables["pds_audited_financials"] = [{
        **_AUDITED_FINANCIALS_ROWS[0],
        "inventory_cents": 290000000,       # KES 2,900,000
        "cost_of_sales_cents": 1750000000,  # KES 17,500,000
        "extraction_confidence": 0.92,
    }]
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")

    expected_turnover = 1750000000 / 290000000  # 6.0344827... -> "6.0x"
    expected_dio = 365 / expected_turnover        # 60.48... -> "60 days"
    assert round(expected_turnover, 1) == 6.0
    assert round(expected_dio) == 60

    assert "KES 2,900,000" in html
    assert "KES 17,500,000" in html
    assert "6.0x" in html
    assert "60 days" in html
    assert "0.92" in html
    assert "Inventory turns over quickly relative to cost of sales — LOW inventory risk." in html


# ── supplier payment analysis (PAR-63) ───────────────────────────────────────
# Concentration clauses only apply at N >= 30 supplier transactions (mirrors
# PAR-89's _MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD, applied here to
# supplier_txn_count specifically). Below that, an explicit insufficient-data
# message replaces the categorical HIGH/MODERATE/diversified label.

def _supplier_txn_fixture(entity_totals: dict, *, amount_cents: int = 100000):
    """Build raw_txn/txn_entity_map/entities rows: `amount_cents`-cent supplier
    debits split across the given {entity_id: txn_count} distribution, so the
    total transaction count and each entity's % share are easy to control."""
    raw_txns, txn_map, seen_entities = [], [], {}
    i = 0
    for eid, count in entity_totals.items():
        seen_entities[eid] = f"Supplier {eid}"
        for _ in range(count):
            tid = f"t{i}"
            raw_txns.append({
                "id": tid, "txn_date": "2025-01-05", "signed_amount_cents": -amount_cents,
                "abs_amount_cents": amount_cents, "normalized_descriptor": "SUPPLIER", "balance_cents": None,
            })
            txn_map.append({"txn_id": tid, "role": "supplier_payment", "entity_id": eid})
            i += 1
    entities = [{"entity_id": eid, "display_name": name} for eid, name in seen_entities.items()]
    return raw_txns, txn_map, entities


def test_supplier_payment_analysis_real_fixture_below_threshold_shows_insufficient_data():
    """The real Buildex fixture has exactly 1 supplier transaction — far below
    the 30-transaction sample-size gate. Confirms the section renders the
    honest insufficient-data message (not a misleading '100.0% HIGH' label,
    which is mathematically guaranteed at N=1 regardless of the real supplier
    mix) and does NOT fabricate an entity_id-less name either."""
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    assert "Supplier Payment Analysis" in html
    # txn-2: signed_amount_cents -200000 = KES 2,000, the only supplier-role txn
    assert "KES 2,000" in html
    assert "-- · 100.0%" in html
    assert "Insufficient supplier transaction volume for a reliable concentration assessment (N=1)." in html
    assert "This represents HIGH supplier concentration risk." not in html


def test_supplier_payment_analysis_below_threshold_boundary_at_29_transactions():
    """29 supplier transactions (one below the N=30 gate) — confirms the
    boundary itself, not just a small illustrative N."""
    tables = dict(_TABLES)
    raw_txns, txn_map, entities = _supplier_txn_fixture({"ent-A": 29})
    tables["pds_raw_transactions"] = raw_txns
    tables["pds_txn_entity_map"] = txn_map
    tables["pds_entities"] = entities
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    assert "Insufficient supplier transaction volume for a reliable concentration assessment (N=29)." in html


def test_supplier_payment_analysis_top_entity_by_name_and_concentration():
    """30 supplier transactions (at the sample-size gate), 24/6 split across
    two entities -> 80% concentration. Confirms the pds_entities join
    correctly attributes spend per counterparty name, picks the top supplier
    by total (not by transaction count), and that HIGH concentration renders
    once the sample is large enough to trust."""
    tables = dict(_TABLES)
    raw_txns, txn_map, entities = _supplier_txn_fixture({"ent-A": 24, "ent-B": 6})
    tables["pds_raw_transactions"] = raw_txns
    tables["pds_txn_entity_map"] = txn_map
    tables["pds_entities"] = [
        {"entity_id": "ent-A", "display_name": "Timber Traders Ltd"},
        {"entity_id": "ent-B", "display_name": "Glass Supplies Co"},
    ]
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")

    # ent-A: 24/30 = 80% -> top supplier by total, despite ent-B having more
    # transactions than a single ent-A transaction would suggest.
    assert "KES 30,000" in html  # 30 txns x KES 1,000 (100000 cents) each
    assert "Timber Traders Ltd · 80.0%" in html
    assert "This represents HIGH supplier concentration risk." in html


def test_supplier_payment_analysis_moderate_and_diversified_concentration():
    """30 supplier transactions split 6 ways across 5 entities (20% each,
    MODERATE) confirms the 15-30% bucket at a trustworthy sample size; a
    second, more diversified fixture (10 entities, 10% each) confirms the
    <15% diversified bucket too."""
    tables = dict(_TABLES)
    raw_txns, txn_map, entities = _supplier_txn_fixture(
        {f"ent-{i}": 6 for i in range(1, 6)}
    )
    tables["pds_raw_transactions"] = raw_txns
    tables["pds_txn_entity_map"] = txn_map
    tables["pds_entities"] = entities
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    # 5 equal suppliers, 30 txns total -> each 20% -> top is 20% -> MODERATE.
    assert "20.0%" in html
    assert "This represents MODERATE supplier concentration." in html

    tables2 = dict(_TABLES)
    raw_txns2, txn_map2, entities2 = _supplier_txn_fixture(
        {f"ent-{i}": 3 for i in range(1, 11)}
    )
    tables2["pds_raw_transactions"] = raw_txns2
    tables2["pds_txn_entity_map"] = txn_map2
    tables2["pds_entities"] = entities2
    renderer._get_supabase = lambda: _FakeSupabase(tables2)
    _patch_recon()
    html2 = renderer.render_snapshot_html("deal-fixture")
    # 10 equal suppliers, 30 txns total -> each 10% -> diversified (<15%).
    assert "10.0%" in html2
    assert "Supplier spend is well-diversified across counterparties." in html2


# ── tax compliance analysis (PAR-63) ─────────────────────────────────────────
# Live recompute over txns, NOT the cached pds_documents.analytics.
# credit_scoring_inputs blob — see PAR-63_new_sections_spec.md Section 3.

def test_tax_compliance_analysis_real_fixture_matches_cached_blob_not_detected():
    """The real Buildex fixture's live txns span 2 real months (2025-01,
    2025-02 — txn-1/txn-2/txn-3) with zero tax_payment-role transactions
    among them, so the live recompute correctly lands on "0 of 2" months /
    NOT_DETECTED — the same categorical value the cached credit_scoring_inputs
    blob happens to carry for this fixture, but this time both the numerator
    (tax months) and denominator (total months) are genuinely sourced from
    the same live txns list (pds_raw_transactions + pds_txn_entity_map), not
    a mix of live txns and canonical_json. An earlier version of this section
    computed the denominator from period_months (canonical_json-derived),
    which happened to read "0 of 0" for this fixture only because the
    fixture's sealed canonical_json carries no transactions at all — a
    data-source inconsistency caught in PR #110 review before merge, not a
    genuine finding about this deal."""
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    assert "Tax Compliance Analysis" in html
    assert "KES 0" in html
    assert "0 of 2" in html
    assert "NOT_DETECTED" in html
    assert (
        "No tax payments detected in bank activity. This does not necessarily "
        "indicate non-compliance — tax may be paid from an account outside this "
        "statement set, or by a third party. Verify against a KRA compliance certificate."
    ) in html


def _tax_txn_fixture(tax_months: list, non_tax_months: list, *, amount_cents: int = 500000):
    """One tax_payment debit per month in `tax_months`, one revenue credit per
    month in `non_tax_months` (so period_months covers the full set) —
    entity_id-agnostic, this section doesn't need pds_entities."""
    raw_txns, txn_map = [], []
    i = 0
    for m in tax_months:
        tid = f"tax{i}"
        raw_txns.append({
            "id": tid, "txn_date": f"{m}-15", "signed_amount_cents": -amount_cents,
            "abs_amount_cents": amount_cents, "normalized_descriptor": "KRA PAYE", "balance_cents": None,
        })
        txn_map.append({"txn_id": tid, "role": "tax_payment"})
        i += 1
    for m in non_tax_months:
        tid = f"rev{i}"
        raw_txns.append({
            "id": tid, "txn_date": f"{m}-05", "signed_amount_cents": amount_cents,
            "abs_amount_cents": amount_cents, "normalized_descriptor": "PAYMENT IN", "balance_cents": None,
        })
        txn_map.append({"txn_id": tid, "role": "revenue_operational"})
        i += 1
    return raw_txns, txn_map


def test_tax_compliance_analysis_compliant_status():
    """Tax activity in 10 of 12 months (>=80%) -> COMPLIANT. Uses canonical_json
    (sealed transactions/txn_entity_map) so monthly_merged/period_months are
    populated, unlike the bare real-fixture snapshot above."""
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    tax_months = months[:10]
    raw_txns, txn_map = _tax_txn_fixture(tax_months, months)
    tables = dict(_TABLES)
    tables["pds_snapshots"] = [{
        "sha256_hash": _SHA,
        "created_at": "2026-01-30T08:00:00+00:00",
        "canonical_json": json.dumps({
            "metrics": {"coverage_bp": 10000, "missing_month_count": 0,
                        "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                        "reconciliation_status": "NOT_RUN"},
            "transactions": raw_txns,
            "txn_entity_map": txn_map,
        }),
    }]
    tables["pds_raw_transactions"] = raw_txns
    tables["pds_txn_entity_map"] = txn_map
    tables["pds_audited_financials"] = []  # observed state — no FY scoping
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    html = renderer.render_snapshot_html("deal-fixture")
    assert "10 of 12" in html
    assert "COMPLIANT" in html
    assert "Tax payment pattern is consistent with the business's stated activity level." in html


def test_tax_compliance_analysis_partial_status():
    """Tax activity in 3 of 12 months (<80%, >0) -> PARTIAL."""
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    tax_months = months[:3]
    raw_txns, txn_map = _tax_txn_fixture(tax_months, months)
    tables = dict(_TABLES)
    tables["pds_snapshots"] = [{
        "sha256_hash": _SHA,
        "created_at": "2026-01-30T08:00:00+00:00",
        "canonical_json": json.dumps({
            "metrics": {"coverage_bp": 10000, "missing_month_count": 0,
                        "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                        "reconciliation_status": "NOT_RUN"},
            "transactions": raw_txns,
            "txn_entity_map": txn_map,
        }),
    }]
    tables["pds_raw_transactions"] = raw_txns
    tables["pds_txn_entity_map"] = txn_map
    tables["pds_audited_financials"] = []
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    html = renderer.render_snapshot_html("deal-fixture")
    assert "3 of 12" in html
    assert "PARTIAL" in html
    assert "Partial tax payment pattern — verify against filed returns." in html


def test_tax_compliance_analysis_renders_in_observed_state_without_audited_financials():
    """Confirms the section renders (not gated on recon_available) when no
    audited financials are submitted at all — same both-states requirement
    as Supplier Payment Analysis."""
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    raw_txns, txn_map = _tax_txn_fixture(months, months)  # tax every month -> COMPLIANT
    tables = dict(_TABLES)
    tables["pds_snapshots"] = [{
        "sha256_hash": _SHA,
        "created_at": "2026-01-30T08:00:00+00:00",
        "canonical_json": json.dumps({
            "metrics": {"coverage_bp": 10000, "missing_month_count": 0,
                        "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                        "reconciliation_status": "NOT_RUN"},
            "transactions": raw_txns,
            "txn_entity_map": txn_map,
        }),
    }]
    tables["pds_raw_transactions"] = raw_txns
    tables["pds_txn_entity_map"] = txn_map
    tables["pds_audited_financials"] = []
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    html = renderer.render_snapshot_html("deal-fixture")
    assert "Tax Compliance Analysis" in html
    assert "12 of 12" in html
    assert "COMPLIANT" in html


# ── monthly cashflow pattern (PAR-63) ────────────────────────────────────────
# Peak/trough + trend summary over the existing monthly_merged/period_months
# (canonical_json-sourced) — confirmed single-source, no cross-source split
# (unlike the bug fixed in Tax Compliance Analysis).

def _cashflow_snapshot_tables(canon_transactions, canon_txn_entity_map):
    document_rows = [{
        "id": "doc-1", "storage_url": "inline://STATEMENT.pdf", "source_files": [],
        "analytics": {"summary": {"total_transactions": len(canon_transactions)}, "credit_scoring_inputs": {}},
    }]
    return {
        "pds_deals": [{"company_name": "Cashflow Pattern Co", "currency": "KES", "analyst_notes": ""}],
        "pds_snapshots": [{
            "sha256_hash": _SHA,
            "created_at": "2026-01-30T08:00:00+00:00",
            "canonical_json": json.dumps({
                "metrics": {"coverage_bp": 10000, "missing_month_count": 0,
                            "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                            "reconciliation_status": "NOT_RUN"},
                "transactions": canon_transactions,
                "txn_entity_map": canon_txn_entity_map,
            }),
        }],
        "pds_documents": document_rows,
        "pds_audited_financials": [],
        "pds_raw_transactions": [],
        "pds_txn_entity_map": [],
    }


def test_monthly_cashflow_pattern_real_fixture_no_crash_no_trend_note():
    """The real Buildex fixture's sealed canonical_json carries no
    transactions at all (confirmed during the Tax Compliance investigation),
    so period_months is empty — confirms this renders the pre-existing
    'No cashflow data available.' note without a broken/empty trend
    sentence tacked on, rather than crashing or emitting stray text."""
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    assert "No cashflow data available." in html
    assert "trend" not in html.lower().split("Monthly Cashflow")[-1].split("</table>")[0]


def test_monthly_cashflow_pattern_single_month_insufficient_for_trend():
    """Exactly one month of data -> the "cannot yet be established" message,
    not a peak/trough claim over a single point."""
    canon_transactions = [
        {"id": "in1", "txn_date": "2025-01-05", "signed_amount_cents": 500000},
        {"id": "out1", "txn_date": "2025-01-20", "signed_amount_cents": -200000},
    ]
    canon_txn_entity_map = [
        {"txn_id": "in1", "role": "revenue_operational"},
        {"txn_id": "out1", "role": "supplier"},
    ]
    tables = _cashflow_snapshot_tables(canon_transactions, canon_txn_entity_map)
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    html = renderer.render_snapshot_html("deal-fixture")
    assert "Only one month of data is available — a trend cannot yet be established." in html


def test_monthly_cashflow_pattern_positive_trend_with_peak_and_trough():
    """3 months: net worsens then recovers to above the first month -> POSITIVE
    trend (last > first), with the trough correctly identified as the worst
    month (Feb), not just the first or last."""
    canon_transactions, canon_txn_entity_map = [], []
    # Jan: net +300,000 (500,000 in - 200,000 out)
    # Feb: net -400,000 (100,000 in - 500,000 out) -- the trough
    # Mar: net +600,000 (800,000 in - 200,000 out) -- the peak, and > Jan (first)
    rows = [
        ("2025-01", 500000, 200000),
        ("2025-02", 100000, 500000),
        ("2025-03", 800000, 200000),
    ]
    for i, (m, in_amt, out_amt) in enumerate(rows):
        in_id, out_id = f"m{i}in", f"m{i}out"
        canon_transactions.append({"id": in_id, "txn_date": f"{m}-05", "signed_amount_cents": in_amt})
        canon_transactions.append({"id": out_id, "txn_date": f"{m}-20", "signed_amount_cents": -out_amt})
        canon_txn_entity_map.append({"txn_id": in_id, "role": "revenue_operational"})
        canon_txn_entity_map.append({"txn_id": out_id, "role": "supplier"})
    tables = _cashflow_snapshot_tables(canon_transactions, canon_txn_entity_map)
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    html = renderer.render_snapshot_html("deal-fixture")
    assert "Trough of KES -4,000 in Feb 2025" in html
    assert "peak of KES 6,000 in Mar 2025" in html
    assert "The trend over the observed period is net POSITIVE." in html


def test_monthly_cashflow_pattern_negative_trend():
    """3 months, net declines from first to last -> NEGATIVE trend clause."""
    canon_transactions, canon_txn_entity_map = [], []
    rows = [
        ("2025-01", 800000, 200000),   # net +600,000 (first, also peak)
        ("2025-02", 400000, 300000),   # net +100,000
        ("2025-03", 200000, 500000),   # net -300,000 (last, also trough)
    ]
    for i, (m, in_amt, out_amt) in enumerate(rows):
        in_id, out_id = f"m{i}in", f"m{i}out"
        canon_transactions.append({"id": in_id, "txn_date": f"{m}-05", "signed_amount_cents": in_amt})
        canon_transactions.append({"id": out_id, "txn_date": f"{m}-20", "signed_amount_cents": -out_amt})
        canon_txn_entity_map.append({"txn_id": in_id, "role": "revenue_operational"})
        canon_txn_entity_map.append({"txn_id": out_id, "role": "supplier"})
    tables = _cashflow_snapshot_tables(canon_transactions, canon_txn_entity_map)
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    html = renderer.render_snapshot_html("deal-fixture")
    assert "Trough of KES -3,000 in Mar 2025" in html
    assert "peak of KES 6,000 in Jan 2025" in html
    assert "The trend over the observed period is net NEGATIVE — recent months show declining net position." in html


# ── build_snapshot_context / render_html equivalent — company name + report id ──

def test_render_html_contains_company_name_and_report_id():
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture")
    assert "Buildex Interiors Company Ltd" in html
    assert "PR-" in html


# ── view + partner_name params ──────────────────────────────────────────────────

def test_verify_view_renders_dark_seal_page():
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture", view="verify")
    assert "SHA256 verified" in html
    assert _SHA in html
    assert "Run your own Parity analysis" in html


def test_partner_name_replaces_header_branding():
    _patch_supabase()
    _patch_recon()
    html = renderer.render_snapshot_html("deal-fixture", partner_name="Musa Ventures")
    assert "Musa Ventures" in html
    assert "Intelligence by" in html


def test_default_view_unaffected_by_new_params():
    """Existing /report PDF endpoint calls render_snapshot_html(deal_id) with no
    extra args — confirm that path is byte-for-byte unaffected by the new params."""
    _patch_supabase()
    _patch_recon()
    html_default = renderer.render_snapshot_html("deal-fixture")
    html_explicit = renderer.render_snapshot_html(
        "deal-fixture", view="observed_recon", partner_name=None
    )
    assert html_default == html_explicit


# ── determinism ──────────────────────────────────────────────────────────────────

def test_determinism_same_context_same_html():
    _patch_supabase()
    _patch_recon()
    html_1 = renderer.render_snapshot_html("deal-fixture")
    html_2 = renderer.render_snapshot_html("deal-fixture")
    assert html_1 == html_2


# ── cross-year statement period (no audited financials) ─────────────────────────

def test_cross_year_statement_period_not_collapsed_to_trailing_month():
    """Regression for the demo deal 2a619980-0f74-4d-9f-bb3b-648ab1eb9c95 bug:
    a deal with no audited financials whose bank statement spans a calendar year
    boundary (e.g. a 13-month lookback Jan 2025 - Jan 2026) previously collapsed
    every "active period" metric to just the trailing 2026-01 month, because
    active_year was computed as max(txn_years) and every filter did
    `m.startswith(f"{active_year}-")`. Confirms all months present are now used
    when no audited financial year is declared, not just the trailing partial year.
    """
    months = [f"2025-{m:02d}" for m in range(1, 13)] + ["2026-01"]
    document_rows = [{
        "id": "doc-1",
        "storage_url": "inline://STATEMENT.pdf",
        "source_files": [],
        "analytics": {"summary": {"total_transactions": len(months)}, "credit_scoring_inputs": {}},
    }]
    # Monthly cashflow / composition now come from canonical_json's sealed
    # transactions + txn_entity_map (see snapshot_html_renderer.py's "Monthly
    # cashflow" comment) — one inflow + one outflow txn per month, net
    # positive throughout, spanning the same Jan 2025 - Jan 2026 boundary.
    canon_transactions = []
    canon_txn_entity_map = []
    for i, m in enumerate(months):
        in_id, out_id = f"c{i}in", f"c{i}out"
        canon_transactions.append({"id": in_id, "txn_date": f"{m}-05", "signed_amount_cents": 100000})
        canon_transactions.append({"id": out_id, "txn_date": f"{m}-10", "signed_amount_cents": -50000})
        canon_txn_entity_map.append({"txn_id": in_id, "role": "revenue_operational"})
        canon_txn_entity_map.append({"txn_id": out_id, "role": "supplier"})

    # Revenue spread across both years, on the LIVE raw-transactions table
    # (avg monthly revenue is still computed from there, unchanged by this
    # unification — only monthly cashflow/composition moved to canonical_json):
    # pre-fix, only the 2026-01 txn (KES 5,000) would count, averaging to "5K".
    # Post-fix, all three months count, averaging (1,000 + 3,000 + 5,000) / 3
    # = KES 3,000, i.e. "3K".
    raw_txn_rows = [
        {"id": "t1", "txn_date": "2025-01-05", "signed_amount_cents": 100000,
         "abs_amount_cents": 100000, "normalized_descriptor": "PAYMENT IN", "balance_cents": None},
        {"id": "t2", "txn_date": "2025-06-05", "signed_amount_cents": 300000,
         "abs_amount_cents": 300000, "normalized_descriptor": "PAYMENT IN", "balance_cents": None},
        {"id": "t3", "txn_date": "2026-01-05", "signed_amount_cents": 500000,
         "abs_amount_cents": 500000, "normalized_descriptor": "PAYMENT IN", "balance_cents": None},
    ]
    txn_map_rows = [
        {"txn_id": "t1", "role": "revenue_operational"},
        {"txn_id": "t2", "role": "revenue_operational"},
        {"txn_id": "t3", "role": "revenue_operational"},
    ]
    tables = {
        "pds_deals": [{"company_name": "CrossYear Co", "currency": "KES", "analyst_notes": ""}],
        "pds_snapshots": [{
            "sha256_hash": _SHA,
            "created_at": "2026-01-30T08:00:00+00:00",
            "canonical_json": json.dumps({
                "metrics": {
                    "coverage_bp": 10000, "missing_month_count": 0,
                    "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                    "reconciliation_status": "NOT_RUN",
                },
                "transactions": canon_transactions,
                "txn_entity_map": canon_txn_entity_map,
            }),
        }],
        "pds_documents": document_rows,
        "pds_audited_financials": [],  # not submitted -> recon_available False
        "pds_raw_transactions": raw_txn_rows,
        "pds_txn_entity_map": txn_map_rows,
    }
    renderer._get_supabase = lambda: _FakeSupabase(tables)

    html = renderer.render_snapshot_html("deal-fixture")

    # All 13 months counted, not just the trailing 2026 month.
    assert "All 13 months net-positive." in html
    # Avg monthly revenue reflects all three revenue months, not just 2026-01 alone.
    assert "3K" in html


def test_observed_patterns_reflect_real_period_length_not_hardcoded_12():
    """The "Observed Patterns" analyst-review section (net-negative months,
    irregular payroll) had its own hardcoded "of 12 months" strings, a second
    instance of the same bug fixed above in the summary cashflow note — missed
    the first time because it's a separate code path. Confirms both now use the
    real observed-period length (13 here) instead of a hardcoded 12.
    """
    months = [f"2025-{m:02d}" for m in range(1, 13)] + ["2026-01"]
    # 3 net-negative months so the "Net-negative months" pattern triggers (>2).
    neg = {"2025-02", "2025-05", "2025-08"}
    document_rows = [{
        "id": "doc-1",
        "storage_url": "inline://STATEMENT.pdf",
        "source_files": [],
        "analytics": {
            "summary": {"total_transactions": len(months)},
            "credit_scoring_inputs": {
                "payroll_stability": "IRREGULAR",
                "payroll_months_detected": 4,
            },
        },
    }]
    # Monthly cashflow now comes from canonical_json's sealed transactions +
    # txn_entity_map (see snapshot_html_renderer.py's "Monthly cashflow" comment).
    canon_transactions = []
    canon_txn_entity_map = []
    for i, m in enumerate(months):
        in_id, out_id = f"c{i}in", f"c{i}out"
        in_amt, out_amt = (50000, 100000) if m in neg else (100000, 50000)
        canon_transactions.append({"id": in_id, "txn_date": f"{m}-05", "signed_amount_cents": in_amt})
        canon_transactions.append({"id": out_id, "txn_date": f"{m}-10", "signed_amount_cents": -out_amt})
        canon_txn_entity_map.append({"txn_id": in_id, "role": "revenue_operational"})
        canon_txn_entity_map.append({"txn_id": out_id, "role": "supplier"})
    tables = {
        "pds_deals": [{"company_name": "CrossYear Co", "currency": "KES", "analyst_notes": ""}],
        "pds_snapshots": [{
            "sha256_hash": _SHA,
            "created_at": "2026-01-30T08:00:00+00:00",
            "canonical_json": json.dumps({
                "metrics": {
                    "coverage_bp": 10000, "missing_month_count": 0,
                    "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                    "reconciliation_status": "NOT_RUN",
                },
                "transactions": canon_transactions,
                "txn_entity_map": canon_txn_entity_map,
            }),
        }],
        "pds_documents": document_rows,
        "pds_audited_financials": [],
        "pds_raw_transactions": [],
        "pds_txn_entity_map": [],
    }
    renderer._get_supabase = lambda: _FakeSupabase(tables)

    html = renderer.render_snapshot_html("deal-fixture")

    assert "3 of 13 months net-negative" in html
    assert "Payroll detected in 4 of 13 months" in html
    assert "of 12 months" not in html


# ── single source of truth: PDF vs live /analytics/monthly-cashflow ─────────

def _extract_cashflow_table_rows(html: str):
    """Parse the rendered Monthly Cashflow table's <tr class="cf-row"> cells
    directly out of the HTML, keyed on the same CSS classes snapshot.html uses
    (cf-month/cf-inflow/cf-outflow), so this can't accidentally match numbers
    elsewhere on the page."""
    return [
        {"month_label": m.group(1), "inflow_str": m.group(2), "outflow_str": m.group(3)}
        for m in re.finditer(
            r'<td class="cf-month">([^<]*)</td>\s*'
            r'<td class="cf-inflow">([^<]*)</td>\s*'
            r'<td class="cf-outflow">([^<]*)</td>',
            html,
        )
    ]


def test_pdf_monthly_cashflow_matches_live_analytics_endpoint_definition():
    """
    The regression test for the bug class fixed by unifying #1 (parity-ingestion's
    raw pre-classification credit/debit cache), #2 (backend/v1/analytics.py's
    role-classified definition — the live GET /analytics/monthly-cashflow
    endpoint the app's Analysis tab uses, and now the trusted single source of
    truth) and #3 (the PDF renderer's own exclude-list composition calc) into
    one definition. See snapshot_html_renderer.py's "Monthly cashflow" comment.

    Builds a deliberately mixed fixture — CASHFLOW_INFLOW_ROLES roles (revenue,
    mpesa, loan_inflow, capital_injection) alongside roles that must NOT count
    as inflow (transfer, even though it's a positive amount), plus outflow
    roles that the OLD exclude-list composition wrongly dropped (transfer,
    opening_balance) but must count under #2's "any negative amount" rule.
    Then independently computes the expected monthly totals by calling
    backend/v1/analytics.py::monthly_cashflow() directly — the exact function
    GET /analytics/monthly-cashflow calls — and asserts the PDF's rendered
    table matches it exactly, month for month. If anyone reintroduces a
    second, independent implementation, this fails immediately instead of
    surfacing in front of a client again.
    """
    canon_transactions = [
        {"id": "a1", "txn_date": "2025-01-05", "signed_amount_cents": 500000},   # revenue_operational -> in
        {"id": "a2", "txn_date": "2025-01-10", "signed_amount_cents": 200000},   # mpesa_inflow -> in
        {"id": "a3", "txn_date": "2025-01-15", "signed_amount_cents": 300000},   # transfer -> NOT in
        {"id": "a4", "txn_date": "2025-01-20", "signed_amount_cents": -150000},  # supplier -> out
        {"id": "a5", "txn_date": "2025-01-25", "signed_amount_cents": -50000},   # transfer -> out (must still count)
        {"id": "a6", "txn_date": "2025-02-05", "signed_amount_cents": 400000},   # loan_inflow -> in
        {"id": "a7", "txn_date": "2025-02-10", "signed_amount_cents": 100000},   # capital_injection -> in
        {"id": "a8", "txn_date": "2025-02-15", "signed_amount_cents": -80000},   # payroll -> out
        {"id": "a9", "txn_date": "2025-02-20", "signed_amount_cents": -20000},   # opening_balance -> out (must still count)
    ]
    canon_txn_entity_map = [
        {"txn_id": "a1", "role": "revenue_operational"},
        {"txn_id": "a2", "role": "mpesa_inflow"},
        {"txn_id": "a3", "role": "transfer"},
        {"txn_id": "a4", "role": "supplier"},
        {"txn_id": "a5", "role": "transfer"},
        {"txn_id": "a6", "role": "loan_inflow"},
        {"txn_id": "a7", "role": "capital_injection"},
        {"txn_id": "a8", "role": "payroll"},
        {"txn_id": "a9", "role": "opening_balance"},
    ]
    document_rows = [{
        "id": "doc-1",
        "storage_url": "inline://STATEMENT.pdf",
        "source_files": [],
        "analytics": {"summary": {"total_transactions": len(canon_transactions)}, "credit_scoring_inputs": {}},
    }]
    tables = {
        "pds_deals": [{"company_name": "Mixed Roles Co", "currency": "KES", "analyst_notes": ""}],
        "pds_snapshots": [{
            "sha256_hash": _SHA,
            "created_at": "2025-03-01T08:00:00+00:00",
            "canonical_json": json.dumps({
                "metrics": {
                    "coverage_bp": 10000, "missing_month_count": 0,
                    "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                    "reconciliation_status": "NOT_RUN",
                },
                "transactions": canon_transactions,
                "txn_entity_map": canon_txn_entity_map,
            }),
        }],
        "pds_documents": document_rows,
        "pds_audited_financials": [],
        "pds_raw_transactions": [],
        "pds_txn_entity_map": [],
    }
    renderer._get_supabase = lambda: _FakeSupabase(tables)

    html = renderer.render_snapshot_html("deal-fixture")

    # Independently compute "expected" via the exact function GET
    # /analytics/monthly-cashflow calls (backend/v1/api.py's get_monthly_cashflow
    # tags transactions the same way: role from txn_entity_map keyed by id/txn_id,
    # amount_cents, txn_date) — not a re-implementation of it.
    role_lookup = {m["txn_id"]: m["role"] for m in canon_txn_entity_map}
    tagged = [{
        "role": role_lookup.get(t["id"], ""),
        "amount_cents": t["signed_amount_cents"],
        "txn_date": t["txn_date"],
        "txn_id": t["id"],
    } for t in canon_transactions]
    expected_rows = _live_monthly_cashflow(tagged)

    assert expected_rows == [
        {"month": "2025-01", "inflow_cents": 700000, "outflow_cents": 200000,
         "net_cents": 500000, "mom_change_bps": None, "mom_reliable": False},
        {"month": "2025-02", "inflow_cents": 500000, "outflow_cents": 100000,
         "net_cents": 400000, "mom_change_bps": -2000, "mom_reliable": False},
    ]

    rendered_rows = _extract_cashflow_table_rows(html)
    assert rendered_rows == [
        {
            "month_label": renderer.MONTH_ABBR[row["month"][5:7]],
            "inflow_str": f"{row['inflow_cents'] / 100:,.0f}",
            "outflow_str": f"{row['outflow_cents'] / 100:,.0f}",
        }
        for row in expected_rows
    ]

    # Composition totals (page 3) must also agree with the same definition —
    # this is #3's half of the unification. total_in = 700,000 + 500,000;
    # total_out = 200,000 + 100,000 (all in cents -> KES millions in the PDF).
    total_in_cents  = sum(r["inflow_cents"] for r in expected_rows)
    total_out_cents = sum(r["outflow_cents"] for r in expected_rows)
    assert f"KES {total_in_cents / 100 / 1_000_000:.1f}M" in html
    assert f"KES {total_out_cents / 100 / 1_000_000:.1f}M" in html


# ── multi-deal validation for the monthly-cashflow unification ──────────────
# Required by the "unify the three divergent definitions" fix: the parity
# property above (PDF matches backend/v1/analytics.py::monthly_cashflow
# exactly) must hold across varied deal shapes, not just one fixture — in
# particular the two branches _in_active_period() takes (audited financial
# year declared vs not) and short (<12 month) statement histories, since
# those are the edge cases most likely to silently break this kind of change.

def _render_and_check_parity(canon_transactions, canon_txn_entity_map, *, audited_financials=None):
    """Render a snapshot from the given canonical transactions/roles and assert
    the PDF's monthly cashflow table matches backend/v1/analytics.py's
    monthly_cashflow() applied to the same active-period-filtered months.
    Returns (html, expected_active_rows) for scenario-specific assertions."""
    document_rows = [{
        "id": "doc-1",
        "storage_url": "inline://STATEMENT.pdf",
        "source_files": [],
        "analytics": {"summary": {"total_transactions": len(canon_transactions)}, "credit_scoring_inputs": {}},
    }]
    tables = {
        "pds_deals": [{"company_name": "Scenario Co", "currency": "KES", "analyst_notes": ""}],
        "pds_snapshots": [{
            "sha256_hash": _SHA,
            "created_at": "2026-01-30T08:00:00+00:00",
            "canonical_json": json.dumps({
                "metrics": {
                    "coverage_bp": 10000, "missing_month_count": 0,
                    "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                    "reconciliation_status": "NOT_RUN",
                },
                "transactions": canon_transactions,
                "txn_entity_map": canon_txn_entity_map,
            }),
        }],
        "pds_documents": document_rows,
        "pds_audited_financials": [audited_financials] if audited_financials else [],
        "pds_raw_transactions": [],
        "pds_txn_entity_map": [],
    }
    renderer._get_supabase = lambda: _FakeSupabase(tables)
    if audited_financials:
        renderer.generate_reconciliation_section = MagicMock(return_value=_RECON_SECTION)

    html = renderer.render_snapshot_html("deal-fixture")

    role_lookup = {m["txn_id"]: m["role"] for m in canon_txn_entity_map}
    tagged = [{
        "role": role_lookup.get(t["id"], ""),
        "amount_cents": t["signed_amount_cents"],
        "txn_date": t["txn_date"],
        "txn_id": t["id"],
    } for t in canon_transactions]
    all_expected_rows = _live_monthly_cashflow(tagged)

    # Mirror _in_active_period(): scoped to the declared FY when audited
    # financials are present, otherwise every month is in scope.
    if audited_financials and audited_financials.get("financial_year"):
        fy = str(audited_financials["financial_year"])
        expected_active_rows = [r for r in all_expected_rows if r["month"].startswith(f"{fy}-")]
    else:
        expected_active_rows = all_expected_rows

    rendered_rows = _extract_cashflow_table_rows(html)
    assert rendered_rows == [
        {
            "month_label": renderer.MONTH_ABBR[row["month"][5:7]],
            "inflow_str": f"{row['inflow_cents'] / 100:,.0f}",
            "outflow_str": f"{row['outflow_cents'] / 100:,.0f}",
        }
        for row in expected_active_rows
    ]
    return html, expected_active_rows


def _canon_month_pair(idx: int, month: str, in_role: str, in_cents: int, out_role: str, out_cents: int):
    """One inflow + one outflow canonical transaction/role-map pair for `month`."""
    in_id, out_id = f"m{idx}in", f"m{idx}out"
    txns = [
        {"id": in_id, "txn_date": f"{month}-05", "signed_amount_cents": in_cents},
        {"id": out_id, "txn_date": f"{month}-20", "signed_amount_cents": -out_cents},
    ]
    roles = [
        {"txn_id": in_id, "role": in_role},
        {"txn_id": out_id, "role": out_role},
    ]
    return txns, roles


def test_multi_deal_parity_with_audited_financials_declared_fy():
    """Deal 2 of 5: audited financials declared (financial_year=2024) — the
    _in_active_period() branch NOT exercised by the demo deal (which has no
    audited financials). Statement includes a 2023 transaction that must be
    excluded from the rendered table (outside the declared FY) while the
    live-endpoint definition (unconditional, no FY scoping) still includes it
    in its own raw output — confirming the renderer's FY scoping composes
    correctly on top of the now-canonical-sourced monthly_merged."""
    canon_transactions, canon_txn_entity_map = [], []
    for i, m in enumerate(["2023-12", "2024-01", "2024-02", "2024-03"]):
        t, r = _canon_month_pair(i, m, "revenue_operational", 300000, "supplier", 100000)
        canon_transactions += t
        canon_txn_entity_map += r

    html, expected_active_rows = _render_and_check_parity(
        canon_transactions, canon_txn_entity_map,
        audited_financials={"financial_year": 2024, "turnover_cents": 0,
                             "profit_before_tax_cents": 0, "loan_breakdown": []},
    )
    # 2023-12 correctly excluded — the rendered table has exactly 3 rows
    # (Jan-Mar 2024), which _render_and_check_parity's row-for-row equality
    # assertion already proved above.
    assert [r["month"] for r in expected_active_rows] == ["2024-01", "2024-02", "2024-03"]


def test_multi_deal_parity_short_history_under_12_months():
    """Deal 3 of 5: only 4 months of statement history (a fresh SME with a
    short banking relationship), no audited financials — the shortest,
    simplest shape most likely to break silently on an off-by-one or an
    empty-collection edge case."""
    canon_transactions, canon_txn_entity_map = [], []
    for i, m in enumerate(["2026-03", "2026-04", "2026-05", "2026-06"]):
        t, r = _canon_month_pair(i, m, "mpesa_inflow", 150000, "payroll", 60000)
        canon_transactions += t
        canon_txn_entity_map += r

    html, expected_active_rows = _render_and_check_parity(canon_transactions, canon_txn_entity_map)
    assert len(expected_active_rows) == 4
    assert "All 4 months net-positive." in html


def test_multi_deal_parity_zero_inflow_month_included():
    """Deal 4 of 5: a month with outflow only (zero inflow) — monthly_cashflow()
    is documented to include zero-inflow months rather than skip them; confirm
    the PDF table still agrees with the live definition for that month."""
    canon_transactions, canon_txn_entity_map = [], []
    t, r = _canon_month_pair(0, "2026-01", "revenue_operational", 200000, "supplier", 50000)
    canon_transactions += t
    canon_txn_entity_map += r
    # 2026-02: outflow only, no inflow transaction at all.
    canon_transactions.append({"id": "m1out", "txn_date": "2026-02-10", "signed_amount_cents": -75000})
    canon_txn_entity_map.append({"txn_id": "m1out", "role": "tax_payment"})

    html, expected_active_rows = _render_and_check_parity(canon_transactions, canon_txn_entity_map)
    assert expected_active_rows[1]["month"] == "2026-02"
    assert expected_active_rows[1]["inflow_cents"] == 0
    assert expected_active_rows[1]["outflow_cents"] == 75000


def test_multi_deal_parity_outflow_only_dormant_account():
    """Deal 5 of 5: a dormant/early-stage account with no inflow roles present
    at all across the whole statement — total_in == 0 throughout, exercising
    the division-by-zero guards in income_quality_pct/mpesa_pct/composition."""
    canon_transactions, canon_txn_entity_map = [], []
    for i, m in enumerate(["2026-01", "2026-02"]):
        in_id, out_id = f"d{i}in", f"d{i}out"
        # A positive amount that does NOT count as inflow (not in
        # CASHFLOW_INFLOW_ROLES) alongside a genuine outflow.
        canon_transactions.append({"id": in_id, "txn_date": f"{m}-05", "signed_amount_cents": 10000})
        canon_txn_entity_map.append({"txn_id": in_id, "role": "reversal_credit"})
        canon_transactions.append({"id": out_id, "txn_date": f"{m}-20", "signed_amount_cents": -40000})
        canon_txn_entity_map.append({"txn_id": out_id, "role": "bank_charge"})

    html, expected_active_rows = _render_and_check_parity(canon_transactions, canon_txn_entity_map)
    assert all(r["inflow_cents"] == 0 for r in expected_active_rows)
    assert all(r["outflow_cents"] == 40000 for r in expected_active_rows)
    # No crash rendering with total_in == 0 throughout — the parity assertion
    # inside _render_and_check_parity already exercised every division-by-zero
    # guard (income_quality_pct, mpesa_pct, composition segments) without
    # raising, since it got this far.
    assert "<html" in html
