"""
PAR-228 — pds_audited_financials must be read with a deterministic ORDER BY.

Before this fix, snapshot_context.py's build_snapshot_context() (and the
equivalent fetch in snapshot_html_renderer.py's render_snapshot_html()) read
pds_audited_financials with no .order()/.limit(), so a deal with 2+ years of
financials would get whichever row PostgREST happened to return first — not
necessarily the most recent fiscal year. This test drives a fake Supabase
client returning multiple financial-year rows in a deliberately non-sorted
order, and asserts the real build_snapshot_context() code path resolves the
Inventory section to the latest fiscal year, matching
reconciliation_engine.py's existing _get_audited_financials() convention
(order by financial_year desc, limit 1).

No real deal currently has multi-year audited financials (confirmed against
real prod data 2026-09-01), so nothing exercises this path today — this is
a synthetic-fixture regression test, per the ticket's own requirement.
"""
from __future__ import annotations

from typing import Any, Dict, List

import v1.analysis.snapshot_context as snapshot_context


class _FakeResult:
    def __init__(self, data: List[Dict[str, Any]]):
        self.data = data


class _FakeQuery:
    """Minimal fluent stand-in for a postgrest-py query builder. Applies real
    order/limit/range semantics against an in-memory row set so a regression
    here (removing .order()/.limit() again) actually breaks this test."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self._all_rows = rows
        self._rows = rows
        self._order_col: str | None = None
        self._order_desc = False
        self._limit: int | None = None
        self._range: tuple[int, int] | None = None

    def select(self, *_a, **_kw):
        return self

    def eq(self, *_a, **_kw):
        return self

    def single(self):
        return self

    def order(self, col: str, desc: bool = False):
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def range(self, start: int, end: int):
        self._range = (start, end)
        return self

    def execute(self):
        rows = list(self._all_rows)
        if self._order_col is not None:
            rows.sort(key=lambda r: r.get(self._order_col), reverse=self._order_desc)
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return _FakeResult(rows)


class _FakeSupabase:
    """Returns empty results for every table except pds_audited_financials,
    which serves the multi-year fixture. build_snapshot_context() handles
    empty upstream data (no snapshot, no transactions, no transfer links)
    gracefully via its existing `or []` / falsy-default guards — this test
    relies on that, not on faking every table's real shape."""

    def __init__(self, audited_financials_rows: List[Dict[str, Any]]):
        self._af_rows = audited_financials_rows

    def table(self, name: str):
        if name == "pds_audited_financials":
            return _FakeQuery(self._af_rows)
        return _FakeQuery([])


def test_inventory_picks_latest_fiscal_year_not_arbitrary_row(monkeypatch):
    # Deliberately inserted with the OLDER year first and a decoy middle row,
    # so a naive af_result[0] (no ORDER BY) would pick the wrong one.
    af_rows = [
        {
            "financial_year": "2024",
            "inventory_cents": 100_000_00,
            "cost_of_sales_cents": 50_000_00,
            "extraction_confidence": 0.9,
            "loan_breakdown": None,
            "turnover_cents": None,
            "profit_before_tax_cents": None,
        },
        {
            "financial_year": "2025",
            "inventory_cents": 200_000_00,
            "cost_of_sales_cents": 80_000_00,
            "extraction_confidence": 0.9,
            "loan_breakdown": None,
            "turnover_cents": None,
            "profit_before_tax_cents": None,
        },
        {
            "financial_year": "2026",
            "inventory_cents": 300_000_00,
            "cost_of_sales_cents": 120_000_00,
            "extraction_confidence": 0.95,
            "loan_breakdown": None,
            "turnover_cents": None,
            "profit_before_tax_cents": None,
        },
    ]

    fake_sb = _FakeSupabase(af_rows)
    monkeypatch.setattr(snapshot_context, "_get_supabase", lambda: fake_sb)
    # Avoid a real network call into reconciliation_engine — irrelevant to
    # this fix, already covered by its own tests (PAR-207 etc).
    monkeypatch.setattr(snapshot_context, "generate_reconciliation_section", lambda deal_id: {})

    ctx = snapshot_context.build_snapshot_context(deal_id="00000000-0000-0000-0000-000000000000")
    inventory = ctx["inventory"]

    assert inventory.available is True
    assert inventory.fiscal_year == "2026"
    assert inventory.inventory.cents == 300_000_00
    assert inventory.cost_of_sales.cents == 120_000_00
