"""
Live-only regression test for the PAR-96 hotfix: TxnEntityMapRepo.count_needs_review_excluding()
originally used .select("*", count="exact", head=True), which silently returns
res.count == 0 regardless of the actual count on this deployment's postgrest-py
(0.17.2) — confirmed live against parity-staging on 2026-08-04, discovered only
because the in-memory test double used everywhere else in this suite doesn't
exercise real PostgREST HTTP/count semantics at all.

Skipped entirely when SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY aren't set (e.g.
this sandbox, most local dev) — this is the one thing in this class of bug
that genuinely cannot be caught without a real Supabase connection. Runs for
real wherever those credentials are present (CI with staging creds, etc.).
"""

import os
import sys

import pytest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

_HAS_LIVE_SUPABASE = bool(os.getenv("SUPABASE_URL")) and bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


@pytest.mark.skipif(
    not _HAS_LIVE_SUPABASE,
    reason="requires live SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY — this specific "
    "regression (head=True silently zeroing count=\"exact\") can only be caught "
    "against a real PostgREST endpoint, not the in-memory test double.",
)
def test_count_needs_review_excluding_matches_real_full_scan():
    from backend.v1.db.supabase_repositories import TxnEntityMapRepo

    repo = TxnEntityMapRepo()
    deal_id = "e21404a2-6bef-4484-a1cb-3fedea4bb2d6"

    # Ground truth: an actual full fetch, same as resolve_transaction() used to
    # do before PAR-96 (deliberately not the method under test).
    full_scan_count = len(repo.list_needs_review_by_deal(deal_id))
    assert full_scan_count > 0, (
        f"Test deal {deal_id} has no needs_review rows right now — this test "
        "needs a live deal with at least one, pick a different one if this deal's "
        "queue has been fully cleared."
    )

    # Excluding a row id that doesn't exist changes nothing, so this must equal
    # the ground truth exactly. Before the hotfix, this silently returned 0.
    counted = repo.count_needs_review_excluding(deal_id, "00000000-0000-0000-0000-000000000000")
    assert counted == full_scan_count, (
        f"count_needs_review_excluding() returned {counted}, expected {full_scan_count} "
        "(PAR-96 head=True regression — see module docstring)"
    )
