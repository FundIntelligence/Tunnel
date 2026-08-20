"""
Tiny DB-fetch helpers shared between snapshot_html_renderer.py and
snapshot_context.py (PAR-189). Split out to avoid a circular import between
the two — snapshot_context.py needs these, and snapshot_html_renderer.py
imports build_snapshot_context() from snapshot_context.py.
"""
from __future__ import annotations

from typing import Dict, List

PAGE_SIZE = 1000


def _get_supabase():
    from ..db.supabase_client import get_supabase
    return get_supabase()


def _paginate(sb, table: str, select_cols: str, deal_id: str) -> List[Dict]:
    rows, offset = [], 0
    while True:
        chunk = (
            sb.table(table)
            .select(select_cols)
            .eq("deal_id", deal_id)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data or []
        )
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows
