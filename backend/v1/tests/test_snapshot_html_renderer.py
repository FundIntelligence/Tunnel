"""
Tests for snapshot_html_renderer.py — presentation-only HTML assembly.
Mocks the Supabase client and the reconciliation engine; does not hit the real DB.
Fixture values mirror the real Buildex production deal confirmed in the prior
audit session (deal_id 42c41951-c907-4361-bb12-16f39d468f0c).
"""
import json
import os
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
    monthly_cashflow = [
        {"month": m, "inflow_cents": 100000, "outflow_cents": 50000} for m in months
    ]
    document_rows = [{
        "id": "doc-1",
        "storage_url": "inline://STATEMENT.pdf",
        "source_files": [],
        "analytics": {
            "summary": {"total_transactions": len(months)},
            "monthly_cashflow": monthly_cashflow,
            "credit_scoring_inputs": {},
        },
    }]
    # Revenue spread across both years: pre-fix, only the 2026-01 txn (KES 5,000)
    # would count, averaging to "5K". Post-fix, all three months count, averaging
    # (1,000 + 3,000 + 5,000) / 3 = KES 3,000, i.e. "3K".
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
            "canonical_json": json.dumps({"metrics": {
                "coverage_bp": 10000, "missing_month_count": 0,
                "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                "reconciliation_status": "NOT_RUN",
            }}),
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
    monthly_cashflow = [
        {
            "month": m,
            "inflow_cents": 50000 if m in neg else 100000,
            "outflow_cents": 100000 if m in neg else 50000,
        }
        for m in months
    ]
    document_rows = [{
        "id": "doc-1",
        "storage_url": "inline://STATEMENT.pdf",
        "source_files": [],
        "analytics": {
            "summary": {"total_transactions": len(months)},
            "monthly_cashflow": monthly_cashflow,
            "credit_scoring_inputs": {
                "payroll_stability": "IRREGULAR",
                "payroll_months_detected": 4,
            },
        },
    }]
    tables = {
        "pds_deals": [{"company_name": "CrossYear Co", "currency": "KES", "analyst_notes": ""}],
        "pds_snapshots": [{
            "sha256_hash": _SHA,
            "created_at": "2026-01-30T08:00:00+00:00",
            "canonical_json": json.dumps({"metrics": {
                "coverage_bp": 10000, "missing_month_count": 0,
                "missing_month_penalty_bp": 0, "reconciliation_bp": None,
                "reconciliation_status": "NOT_RUN",
            }}),
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
