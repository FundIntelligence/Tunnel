"""
backend/v1/analytics.py::monthly_cashflow — MoM change regression lock.

Confirms the NaN%* bug (mom_change_bps/mom_reliable were never emitted) stays
fixed, and that the pre-existing return fields are unchanged.
"""

import os
import sys
import unittest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.v1.analytics import monthly_cashflow


def _txn(date, amount_cents, role):
    return {"txn_id": f"t-{date}-{amount_cents}", "txn_date": date, "amount_cents": amount_cents, "role": role}


class TestMonthlyCashflowMoMChange(unittest.TestCase):
    def test_first_month_has_no_mom_change(self):
        rows = monthly_cashflow([
            _txn("2025-01-05", 500_000, "revenue_operational"),
            _txn("2025-01-10", -100_000, "supplier"),
        ])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["mom_change_bps"])
        self.assertFalse(rows[0]["mom_reliable"])
        # explicit non-NaN-producing contract: must be exactly None, not a float NaN
        self.assertNotIsInstance(rows[0]["mom_change_bps"], float)

    def test_normal_month_mom_change_matches_hand_calculation(self):
        rows = monthly_cashflow([
            _txn("2025-01-05", 2_000_000, "revenue_operational"),  # Jan net = 2,000,000
            _txn("2025-02-05", 2_500_000, "revenue_operational"),  # Feb net = 2,500,000
        ])
        self.assertEqual(len(rows), 2)
        jan, feb = rows
        self.assertEqual(jan["net_cents"], 2_000_000)
        self.assertEqual(feb["net_cents"], 2_500_000)
        # (2,500,000 - 2,000,000) * 10000 // 2,000,000 = 2500 bps (+25.00%)
        self.assertEqual(feb["mom_change_bps"], 2500)
        # prior month net (2,000,000) >= 1,000,000 threshold -> reliable
        self.assertTrue(feb["mom_reliable"])

    def test_mom_unreliable_below_threshold(self):
        rows = monthly_cashflow([
            _txn("2025-01-05", 500_000, "revenue_operational"),  # Jan net = 500,000 (< 1,000,000 threshold)
            _txn("2025-02-05", 600_000, "revenue_operational"),  # Feb net = 600,000
        ])
        feb = rows[1]
        self.assertIsNotNone(feb["mom_change_bps"])
        self.assertFalse(feb["mom_reliable"])

    def test_existing_return_fields_unchanged(self):
        rows = monthly_cashflow([
            _txn("2025-01-05", 500_000, "revenue_operational"),
            _txn("2025-01-10", -100_000, "supplier"),
        ])
        row = rows[0]
        self.assertEqual(row["month"], "2025-01")
        self.assertEqual(row["inflow_cents"], 500_000)
        self.assertEqual(row["outflow_cents"], 100_000)
        self.assertEqual(row["net_cents"], 400_000)
        self.assertEqual(
            set(row.keys()),
            {"month", "inflow_cents", "outflow_cents", "net_cents", "mom_change_bps", "mom_reliable"},
        )


if __name__ == "__main__":
    unittest.main()
