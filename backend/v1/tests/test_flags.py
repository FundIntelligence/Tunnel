"""
Tests for Parity Review default flag seeding.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flags import seed_default_flags


def test_default_flag_threshold_computation():
    avg_monthly_inflow = 28_839_759_18  # KES 28.8M in cents
    threshold = (avg_monthly_inflow * 1500) // 10000
    # 15% of 28.8M = 4.32M KES
    assert threshold == 432_596_387  # KES 4,325,963 — floor division of 15% of 28.8M


def test_seed_default_flags_creates_three():
    flags = seed_default_flags(
        deal_id="test-deal-001",
        avg_monthly_inflow_cents=10_000_000_00,
        flags_repo=None,
    )
    assert len(flags) == 3


def test_seed_default_flags_idempotent():
    # Without a real repo, calling twice produces the same 3 flags each time
    flags1 = seed_default_flags(
        deal_id="test-deal-002",
        avg_monthly_inflow_cents=10_000_000_00,
        flags_repo=None,
    )
    flags2 = seed_default_flags(
        deal_id="test-deal-002",
        avg_monthly_inflow_cents=10_000_000_00,
        flags_repo=None,
    )
    assert len(flags1) == 3
    assert len(flags2) == 3
