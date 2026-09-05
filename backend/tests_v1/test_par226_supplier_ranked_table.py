"""
PAR-226 — Supplier Payment Analysis: surface the already-computed ranked
supplier table (top-10, every deal regardless of size), replace the
"well-diversified" narrative with a factual concentration stat.

Fixture shape mirrors real prod data pulled from deal
7614e320-e3d0-43af-8d2a-fa25cbef08ab (ifcdbhbuucmjgtjkluna) 2026-09-01 —
6+ named suppliers with real transaction-count/amount spread — rather than
a synthetic round-numbers case, per PAR-226's "test against real deal shapes"
verification requirement.
"""
from __future__ import annotations

from typing import Any, Dict, List

from v1.analysis.snapshot_context import (
    DEFAULT_SUPPLIER_CONCENTRATION_CONFIG,
    SupplierEntry,
    _build_supplier_payments,
)
from v1.analysis.snapshot_html_renderer import _supplier_payments_ctx_from


def _txn(role: str, signed: int, entity_id: str) -> Dict[str, Any]:
    return {"role": role, "signed": signed, "abs": abs(signed), "entity_id": entity_id}


def _real_shape_txns() -> List[Dict[str, Any]]:
    # (entity, per-txn amount cents, txn count) — matches real supplier totals
    # observed on deal 7614e320: El Jireh 2,634,000 KES/13, Eazzybiz-A
    # 2,500,000/1, Erdema 2,000,000/1, Grace Njeri 1,537,000/6 (KES -> cents).
    suppliers = [
        ("el_jireh", -20_261_538, 13),   # ~263,400,000 cents total / 13
        ("eazzybiz_a", -250_000_000, 1),
        ("erdema", -200_000_000, 1),
        ("grace_njeri", -25_616_667, 6),  # ~153,700,000 cents total / 6
        ("eazzybiz_b", -153_500_000, 1),
        ("eazzybiz_c", -149_600_000, 1),
        # long tail — 20 more small suppliers, to confirm the top-10 cutoff
        # actually caps the table rather than rendering everything.
    ] + [(f"tail_{i}", -10_000_00, 1) for i in range(20)]

    txns = []
    for eid, amount, count in suppliers:
        for _ in range(count):
            txns.append(_txn("supplier_payment", amount, eid))
    return txns


def test_top_n_ranked_by_total_desc_capped_at_ten():
    sp = _build_supplier_payments(
        _real_shape_txns(),
        entity_name_by_id={
            "el_jireh": "Transfer Fuel payment EL JIREH LOGISTICS",
            "eazzybiz_a": "EAZZYBIZ TRSF BIASHARA C76420012508",
            "erdema": "RTGS: RTOBZN04517099 ERDEMA",
            "grace_njeri": "Transfer laminated doors GRACE NJERI MUC",
            "eazzybiz_b": "EAZZYBIZ TRSF BIASHARA C75912032508",
            "eazzybiz_c": "EAZZYBIZ TRSF BIASHARA C76515052507",
        },
        config=DEFAULT_SUPPLIER_CONCENTRATION_CONFIG,
    )

    assert sp.available is True
    assert sp.top_n is not None
    # 26 distinct suppliers computed; table caps at 10, not the full list.
    assert sp.counterparty_count == 26
    assert len(sp.top_n) == 10

    # Ranked strictly descending by total value.
    totals = [row.total.cents for row in sp.top_n]
    assert totals == sorted(totals, reverse=True)

    # Rank #1 matches the real top supplier (El Jireh, per real prod data).
    assert sp.top_n[0].name == "Transfer Fuel payment EL JIREH LOGISTICS"
    assert sp.top_n[0].txn_count == 13

    # Every entry carries name/count/amount only — no interpretive field.
    for row in sp.top_n:
        assert isinstance(row, SupplierEntry)
        assert row.share.value == row.total.cents / sp.total.cents


def test_diversified_narrative_has_no_adjective_and_states_the_figure():
    # Many small, roughly-even suppliers -> DIVERSIFIED bucket (top share < 15%).
    txns = [_txn("supplier_payment", -10_000_00, f"s{i}") for i in range(40)]
    sp = _build_supplier_payments(txns, entity_name_by_id={}, config=DEFAULT_SUPPLIER_CONCENTRATION_CONFIG)

    assert sp.concentration == "DIVERSIFIED"
    assert "well-diversified" not in sp.narrative
    assert "diversified" not in sp.narrative.lower()
    # Factual: names the percentage and counterparty count, nothing else.
    top_pct = sp.top_share.value * 100
    assert f"{top_pct:.1f}%" in sp.narrative
    assert str(sp.counterparty_count) in sp.narrative


def test_renderer_ctx_exposes_rows_for_template():
    sp = _build_supplier_payments(
        _real_shape_txns(),
        entity_name_by_id={"el_jireh": "EL JIREH LOGISTICS"},
        config=DEFAULT_SUPPLIER_CONCENTRATION_CONFIG,
    )
    ctx = _supplier_payments_ctx_from(sp)

    assert len(ctx["rows"]) == 10
    first = ctx["rows"][0]
    assert first["name"] == "EL JIREH LOGISTICS"
    assert first["txn_count"] == 13
    assert "KES" in first["total_str"]
    assert first["pct_str"].endswith("%")


def test_unavailable_state_has_no_rows_key_crash():
    sp = _build_supplier_payments([], entity_name_by_id={}, config=DEFAULT_SUPPLIER_CONCENTRATION_CONFIG)
    ctx = _supplier_payments_ctx_from(sp)
    assert ctx == {"available": False}
