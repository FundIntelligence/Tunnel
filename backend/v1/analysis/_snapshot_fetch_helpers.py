"""
Tiny helpers shared between snapshot_html_renderer.py and
snapshot_context.py (PAR-189). Split out to avoid a circular import between
the two — snapshot_context.py needs these, and snapshot_html_renderer.py
imports build_snapshot_context() from snapshot_context.py.

Mostly DB-fetch helpers. PAR-189 Stage 7 also moved _BANK_ALIASES/_bank_label
here (unchanged) for the same circular-import reason: Inter-Account Transfer
Analysis names each side of a detected transfer pair from the document's
detected bank label, so snapshot_context.py now needs the same lookup
snapshot_html_renderer.py already used. snapshot_html_renderer.py re-imports
_bank_label from here, so `renderer._bank_label(...)` still resolves for
existing callers and tests.
"""
from __future__ import annotations

from typing import Dict, List, Optional

PAGE_SIZE = 1000

_BANK_ALIASES = [
    ("KCB",         ["kcb", "kenya commercial bank"]),
    ("Equity",      ["equity"]),
    ("Absa",        ["absa", "barclays"]),
    ("Zemo",        ["zemo"]),
    ("NCBA",        ["ncba", "nic bank", "commercial bank of africa"]),
    ("Co-op",       ["co-operative bank", "coop bank", "co-op"]),
    ("DTB",         ["dtb", "diamond trust"]),
    ("Stanbic",     ["stanbic"]),
    ("IM Bank",     ["im bank", "imperial bank"]),
    ("Family Bank", ["family bank"]),
    ("Prime Bank",  ["prime bank"]),
]


def _bank_label(url: str) -> Optional[str]:
    n = (url or "").lower()
    for key, aliases in _BANK_ALIASES:
        if any(a in n for a in aliases):
            return key
    return None


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
