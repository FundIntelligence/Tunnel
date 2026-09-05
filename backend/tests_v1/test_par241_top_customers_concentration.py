"""
PAR-241 — Top Customers (top_revenue) concentration section.

Root cause confirmed against real prod/staging data before this fix: for the
Buildex verification deal (18e61840-d8dd-46a5-aa3d-5e1d3fafdd33, paritystaging),
top_revenue was genuinely populated (10,055 transactions tagged
revenue_operational, aggregating into distinct named entities with material
amounts) -- this was hypothesis 1 (rendering/label issue), not hypothesis 2
(empty tagging). "Top revenue entities" simply didn't read as "customers" on a
quick scan.

This suite covers the three fixes made in pdf_generator.py's 06 CONCENTRATION
section:
  1. Relabel "Top revenue entities" -> "Top customers" (parallels "Top suppliers").
  2. Render up to 10 rows for both top_suppliers/top_revenue, matching what
     context.py already computes (was capped at 5 in pdf_generator.py only).
  3. An empty list renders an explicit "No concentration data available"
     fallback line instead of silently vanishing with no trace.
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

try:
    from v1.core.pdf_generator import generate_pdf
    from pypdf import PdfReader
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False


def _make_canonical(n_revenue_entities: int, n_supplier_entities: int) -> dict:
    """Build a minimal canonical dict with N distinct revenue/supplier entities,
    each with 3 transactions, so entity_breakdown aggregates like real data
    rather than degenerating into one-transaction-per-entity."""
    txns, entities, tmap = [], [], []
    tid = 0
    for i in range(n_revenue_entities):
        eid = f"rev{i}"
        entities.append({"entity_id": eid, "display_name": f"Customer {i}"})
        for _ in range(3):
            tid += 1
            txns.append({"id": str(tid), "signed_amount_cents": (100 - i) * 10000, "txn_date": "2025-01-01"})
            tmap.append({"entity_id": eid, "txn_id": str(tid), "role": "revenue_operational"})
    for i in range(n_supplier_entities):
        eid = f"sup{i}"
        entities.append({"entity_id": eid, "display_name": f"Supplier {i}"})
        tid += 1
        txns.append({"id": str(tid), "signed_amount_cents": -(100 - i) * 10000, "txn_date": "2025-01-01"})
        tmap.append({"entity_id": eid, "txn_id": str(tid), "role": "supplier_payment"})
    return {
        "deal_id": "test-deal", "currency": "KES",
        "transactions": txns, "entities": entities, "txn_entity_map": tmap,
        "metrics": {}, "confidence": {}, "reconciliation_summary": {},
        "overrides_applied": [],
    }


def _pdf_text(canonical: dict) -> str:
    pdf_bytes = generate_pdf(canonical)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@unittest.skipUnless(_DEPS_AVAILABLE, "reportlab/pypdf not installed")
class TestTopCustomersRelabel(unittest.TestCase):
    def test_populated_list_uses_top_customers_label_not_old_label(self):
        text = _pdf_text(_make_canonical(n_revenue_entities=8, n_supplier_entities=8))
        self.assertIn("Top customers:", text)
        self.assertNotIn("Top revenue entities", text)

    def test_renders_up_to_ten_rows_not_five(self):
        # 8 revenue entities ranked by descending amount (Customer 0 is largest);
        # the pre-fix 5-row cap would have dropped Customer 5/6/7 entirely.
        text = _pdf_text(_make_canonical(n_revenue_entities=8, n_supplier_entities=0))
        for i in range(8):
            self.assertIn(f"Customer {i}", text)

    def test_caps_at_ten_rows_when_more_than_ten_entities(self):
        text = _pdf_text(_make_canonical(n_revenue_entities=12, n_supplier_entities=0))
        # Scope to the 06 CONCENTRATION section specifically -- section 05
        # ENTITY BREAKDOWN legitimately lists up to 50 entities and would
        # otherwise make this assertion meaningless.
        concentration_text = text.split("06 CONCENTRATION", 1)[1]
        for i in range(10):
            self.assertIn(f"Customer {i}", concentration_text)
        # 11th/12th-largest (lowest-amount) entities fall outside the top-10 cap.
        self.assertNotIn("Customer 10", concentration_text)
        self.assertNotIn("Customer 11", concentration_text)


@unittest.skipUnless(_DEPS_AVAILABLE, "reportlab/pypdf not installed")
class TestConcentrationEmptyFallback(unittest.TestCase):
    def test_empty_top_revenue_shows_fallback_not_silence(self):
        text = _pdf_text(_make_canonical(n_revenue_entities=0, n_supplier_entities=3))
        self.assertIn("Top customers: No concentration data available.", text)
        # Suppliers side is populated, should render normally, not the fallback.
        self.assertNotIn("Top suppliers: No concentration data available.", text)

    def test_empty_top_suppliers_shows_fallback_not_silence(self):
        text = _pdf_text(_make_canonical(n_revenue_entities=3, n_supplier_entities=0))
        self.assertIn("Top suppliers: No concentration data available.", text)
        self.assertNotIn("Top customers: No concentration data available.", text)

    def test_both_empty_shows_both_fallbacks(self):
        text = _pdf_text(_make_canonical(n_revenue_entities=0, n_supplier_entities=0))
        self.assertIn("Top suppliers: No concentration data available.", text)
        self.assertIn("Top customers: No concentration data available.", text)


if __name__ == "__main__":
    unittest.main()
