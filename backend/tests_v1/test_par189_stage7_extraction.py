"""
PAR-189 Stage 7 verification — Inter-Account Transfer Analysis extraction into
build_snapshot_context().

Same pattern as Stages 1-6: the real acceptance bar is a full-document
byte-diff of render_snapshot_html()'s HTML output on the real Deed document,
old path vs new (run separately; PASS, byte-identical, reported on PAR-189).
This file verifies the presentation dict (badge_label/pairs/note/
override_note) is byte-identical between the ORIGINAL inline computation
(transcribed verbatim from the pre-Stage-7 source — snapshot_html_renderer.py
lines 849-937 as merged through PR #166) and the NEW
build_snapshot_context() + adapter path.

Why these fixtures carry real weight here: the real Deed deal has ZERO
pds_transfer_links rows and exactly ONE distinct account_id ("default"), so
the real document only ever exercises the UNAVAILABLE branch. The DETECTED
and NO_TRANSFERS_FOUND branches — including pair aggregation, sorting, and
the bank-label fallback chain — are covered ONLY by the scenarios below.
That gap is flagged explicitly in the Stage 7 report rather than being
papered over by the byte-identical headline.
"""
from __future__ import annotations

from collections import defaultdict

import pytest

from v1.analysis._snapshot_fetch_helpers import _bank_label
from v1.analysis.snapshot_context import (
    Money,
    _build_inter_account_transfer,
)
from v1.analysis.snapshot_html_renderer import _inter_account_transfer_ctx_from


def _fmt_kes(cents: int) -> str:
    return f"KES {cents / 100:,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL logic, transcribed verbatim from the pre-Stage-7 source
# (backend/v1/analysis/snapshot_html_renderer.py as merged through PR #166).
# ─────────────────────────────────────────────────────────────────────────────

def _original_inter_account_transfer(txns, txn_rows, transfer_link_rows, doc_bank_by_id):
    _TRANSFER_ROLES = ("transfer", "internal_transfer")
    manual_transfer_count = sum(1 for t in txns if t["role"] in _TRANSFER_ROLES)

    if manual_transfer_count > 0:
        transfer_override_note = (
            f"{manual_transfer_count} transaction(s) were manually flagged by an analyst "
            "as self-transfers via override — see the Overrides section. This is "
            "analyst-asserted, not system-detected, and does not reflect automatic "
            "self-transfer/cash-sweep detection."
        )
    else:
        transfer_override_note = (
            "No transactions have been manually flagged as self-transfers for this deal."
        )

    document_id_by_txn = {t["id"]: t.get("document_id") for t in txn_rows}
    distinct_account_ids = {t.get("account_id") for t in txn_rows if t.get("account_id")}

    def _account_label(txn_id, fallback):
        doc_id = document_id_by_txn.get(txn_id)
        return doc_bank_by_id.get(doc_id) or (f"Account {doc_id[:8]}" if doc_id else fallback)

    if transfer_link_rows:
        total_count = len(transfer_link_rows)
        total_cents = sum(l["abs_amount_cents"] for l in transfer_link_rows)
        pair_agg = defaultdict(lambda: {"count": 0, "cents": 0})
        for link in transfer_link_rows:
            out_label = _account_label(link["txn_out_id"], "Account A")
            in_label = _account_label(link["txn_in_id"], "Account B")
            key = f"{out_label} -> {in_label}"
            pair_agg[key]["count"] += 1
            pair_agg[key]["cents"] += link["abs_amount_cents"]
        transfer_pairs = [
            {"label": key, "count": agg["count"], "total_str": _fmt_kes(agg["cents"])}
            for key, agg in sorted(pair_agg.items())
        ]
        inter_account_transfer_note = (
            f"{total_count} inter-account transfer pair(s) detected between this company's own "
            f"bank accounts, totaling {_fmt_kes(total_cents)}. Detected automatically by pairing "
            "same-amount, opposite-sign transactions across different accounts within a short "
            "window — see the breakdown above."
        )
        inter_account_badge = "Detected"
    elif len(distinct_account_ids) >= 2:
        transfer_pairs = []
        inter_account_transfer_note = (
            "Self-transfer / cash-sweep detection ran for this deal — transactions are tagged "
            "with distinct per-account identifiers — and found no qualifying inter-account "
            "transfer pairs in this period. This is a genuine result, not an infrastructure gap."
        )
        inter_account_badge = "No Transfers Found"
    else:
        transfer_pairs = []
        inter_account_transfer_note = (
            "Self-transfer / cash-sweep analysis between this company's own bank accounts "
            "is not currently available. Detection depends on each transaction being tagged "
            "with the specific account it belongs to, and that per-account tagging is not "
            "yet populated correctly in the current ingestion pipeline — every transaction "
            "currently resolves to the same undifferentiated account value, so the matching "
            "logic cannot distinguish between a company's own accounts. This is a known "
            "infrastructure gap, not a finding that no such transfers exist."
        )
        inter_account_badge = "Not Available"

    return {
        "badge_label": inter_account_badge,
        "pairs": transfer_pairs,
        "note": inter_account_transfer_note,
        "override_note": transfer_override_note,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _txn(txn_id, role="other", account_id=None, document_id=None):
    """
    Stage 7 unified the original's two separate inputs (`txns` for roles,
    `txn_rows` for account_id/document_id) onto the single txn dict
    _fetch_txns_for_context() now returns. Both original inputs are derived
    from this one fixture row so the transcribed original and the new path see
    identical data.
    """
    return {
        "id": txn_id,
        "role": role,
        "account_id": account_id,
        "document_id": document_id,
        "txn_date": "2026-01-15",
        "signed": -1000,
        "abs": 1000,
        "desc": "",
        "entity_id": None,
    }


def _link(out_id, in_id, cents):
    return {"txn_out_id": out_id, "txn_in_id": in_id, "abs_amount_cents": cents}


def _assert_equivalent(txns, links, doc_bank_by_id):
    """Original inline dict must equal the new builder+adapter dict, exactly."""
    original = _original_inter_account_transfer(txns, txns, links, doc_bank_by_id)
    new = _inter_account_transfer_ctx_from(
        _build_inter_account_transfer(txns, links, doc_bank_by_id, "KES")
    )
    # PAR-208 adds a `state` key carrying the raw semantic detection state, so
    # the methodology appendix can say whether transfer matching is actually
    # running rather than hardcoding it. The pre-Stage-7 original never emitted
    # that key. It is additive and changes none of the fields this oracle was
    # written to protect, so it is dropped before the comparison —
    # _original_inter_account_transfer() stays a frozen transcription of 2026-era
    # behaviour, and editing it to add a key it never had would defeat its
    # purpose. `state` has its own direct coverage in
    # test_par208_methodology_appendix.py::test_renderer_passes_transfer_state_through.
    assert {k: v for k, v in new.items() if k != "state"} == original
    return new


# ─────────────────────────────────────────────────────────────────────────────
# Branch 3 — UNAVAILABLE (the ONLY branch the real Deed document exercises)
# ─────────────────────────────────────────────────────────────────────────────

def test_unavailable_matches_real_deed_shape():
    """Zero links + a single undifferentiated account_id — Deed's real state."""
    txns = [_txn(f"t{i}", account_id="default", document_id="doc-a") for i in range(5)]
    ctx = _assert_equivalent(txns, [], {"doc-a": None})
    assert ctx["badge_label"] == "Not Available"
    assert ctx["pairs"] == []
    assert "known infrastructure gap" in ctx["note"]
    assert ctx["override_note"].startswith("No transactions have been manually flagged")


def test_unavailable_when_no_account_ids_at_all():
    txns = [_txn("t1"), _txn("t2")]
    ctx = _assert_equivalent(txns, [], {})
    assert ctx["badge_label"] == "Not Available"


def test_unavailable_is_not_reported_as_genuine_zero():
    """
    The load-bearing distinction: a tagging gap must never render as
    "detection ran and found nothing". Guards the two notes against being
    collapsed into one.
    """
    txns = [_txn("t1", account_id="default")]
    ctx = _assert_equivalent(txns, [], {})
    assert "This is a genuine result" not in ctx["note"]
    assert "not a finding that no such transfers exist" in ctx["note"]


# ─────────────────────────────────────────────────────────────────────────────
# Branch 2 — NO_TRANSFERS_FOUND (fixture-only; real Deed cannot reach this)
# ─────────────────────────────────────────────────────────────────────────────

def test_no_transfers_found_with_two_distinct_accounts():
    txns = [_txn("t1", account_id="acct-1"), _txn("t2", account_id="acct-2")]
    ctx = _assert_equivalent(txns, [], {})
    assert ctx["badge_label"] == "No Transfers Found"
    assert ctx["pairs"] == []
    assert "This is a genuine result, not an infrastructure gap." in ctx["note"]


def test_null_account_ids_do_not_count_toward_distinct_total():
    """None account_ids are filtered out, so these stay UNAVAILABLE, not genuine-zero."""
    txns = [_txn("t1", account_id="acct-1"), _txn("t2", account_id=None)]
    ctx = _assert_equivalent(txns, [], {})
    assert ctx["badge_label"] == "Not Available"


# ─────────────────────────────────────────────────────────────────────────────
# Branch 1 — DETECTED (fixture-only; real Deed has zero transfer_links)
# ─────────────────────────────────────────────────────────────────────────────

def test_detected_single_pair_with_bank_labels():
    txns = [
        _txn("out1", account_id="a1", document_id="doc-eq"),
        _txn("in1", account_id="a2", document_id="doc-kcb"),
    ]
    ctx = _assert_equivalent(
        txns, [_link("out1", "in1", 250000)], {"doc-eq": "Equity", "doc-kcb": "KCB"},
    )
    assert ctx["badge_label"] == "Detected"
    assert ctx["pairs"] == [{"label": "Equity -> KCB", "count": 1, "total_str": "KES 2,500"}]
    assert "1 inter-account transfer pair(s) detected" in ctx["note"]
    assert "totaling KES 2,500" in ctx["note"]


def test_detected_aggregates_and_sorts_multiple_routes():
    txns = [
        _txn("o1", account_id="a1", document_id="doc-kcb"),
        _txn("i1", account_id="a2", document_id="doc-eq"),
        _txn("o2", account_id="a1", document_id="doc-kcb"),
        _txn("i2", account_id="a2", document_id="doc-eq"),
        _txn("o3", account_id="a2", document_id="doc-eq"),
        _txn("i3", account_id="a1", document_id="doc-kcb"),
    ]
    links = [
        _link("o1", "i1", 100000),
        _link("o2", "i2", 300000),
        _link("o3", "i3", 50000),
    ]
    ctx = _assert_equivalent(txns, links, {"doc-kcb": "KCB", "doc-eq": "Equity"})
    # sorted() on the route key -> "Equity -> KCB" precedes "KCB -> Equity"
    assert [p["label"] for p in ctx["pairs"]] == ["Equity -> KCB", "KCB -> Equity"]
    assert ctx["pairs"][1] == {"label": "KCB -> Equity", "count": 2, "total_str": "KES 4,000"}
    assert ctx["pairs"][0] == {"label": "Equity -> KCB", "count": 1, "total_str": "KES 500"}
    assert "3 inter-account transfer pair(s) detected" in ctx["note"]


def test_detected_falls_back_to_truncated_document_id():
    """No bank label -> 'Account <first 8 chars of document_id>'."""
    txns = [
        _txn("out1", account_id="a1", document_id="abcdefgh-1234-5678"),
        _txn("in1", account_id="a2", document_id="zyxwvuts-1234-5678"),
    ]
    ctx = _assert_equivalent(txns, [_link("out1", "in1", 1000)], {})
    assert ctx["pairs"][0]["label"] == "Account abcdefgh -> Account zyxwvuts"


def test_detected_falls_back_to_positional_label_when_document_id_missing():
    txns = [_txn("out1", account_id="a1"), _txn("in1", account_id="a2")]
    ctx = _assert_equivalent(txns, [_link("out1", "in1", 1000)], {})
    assert ctx["pairs"][0]["label"] == "Account A -> Account B"


def test_detected_wins_even_with_degenerate_account_tagging():
    """
    Fidelity point #1 from the builder docstring: the DETECTED branch is gated
    on transfer_link_rows ALONE. A deal with real links but only one distinct
    account_id still renders the real breakdown, NOT the limitation stub.
    """
    txns = [
        _txn("out1", account_id="default", document_id="doc-eq"),
        _txn("in1", account_id="default", document_id="doc-kcb"),
    ]
    ctx = _assert_equivalent(
        txns, [_link("out1", "in1", 7500)], {"doc-eq": "Equity", "doc-kcb": "KCB"},
    )
    assert ctx["badge_label"] == "Detected"
    assert ctx["pairs"][0]["label"] == "Equity -> KCB"


# ─────────────────────────────────────────────────────────────────────────────
# Analyst-override note — independent of system detection (fidelity point #2)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["transfer", "internal_transfer"])
def test_override_note_counts_both_transfer_roles(role):
    txns = [_txn("t1", role=role, account_id="default"), _txn("t2", account_id="default")]
    ctx = _assert_equivalent(txns, [], {})
    assert ctx["override_note"].startswith("1 transaction(s) were manually flagged")
    assert "analyst-asserted, not system-detected" in ctx["override_note"]


def test_override_note_coexists_with_unavailable_detection():
    """
    Fidelity point #2: analyst overrides and system detection are separate
    claims. A deal can carry overrides while detection reports UNAVAILABLE —
    the two notes must not be merged or allowed to suppress one another.
    """
    txns = [_txn("t1", role="transfer", account_id="default") for _ in range(3)]
    ctx = _assert_equivalent(txns, [], {})
    assert ctx["badge_label"] == "Not Available"
    assert ctx["override_note"].startswith("3 transaction(s) were manually flagged")


def test_override_note_coexists_with_detected():
    txns = [
        _txn("out1", role="transfer", account_id="a1", document_id="doc-eq"),
        _txn("in1", account_id="a2", document_id="doc-kcb"),
    ]
    ctx = _assert_equivalent(
        txns, [_link("out1", "in1", 1000)], {"doc-eq": "Equity", "doc-kcb": "KCB"},
    )
    assert ctx["badge_label"] == "Detected"
    assert ctx["override_note"].startswith("1 transaction(s) were manually flagged")


# ─────────────────────────────────────────────────────────────────────────────
# Typed-schema assertions (PAR-189 ratified conventions)
# ─────────────────────────────────────────────────────────────────────────────

def test_state_is_semantic_not_a_badge_string():
    """Decision #5: the shared context must not carry presentation labels."""
    txns = [_txn("t1", account_id="default")]
    iat = _build_inter_account_transfer(txns, [], {}, "KES")
    assert iat.state == "UNAVAILABLE"
    assert "Not Available" not in iat.state


def test_missing_total_is_null_plus_reason_not_a_sentinel():
    """Decision #1: null value + separate reason field, never an overloaded string."""
    txns = [_txn("t1", account_id="a1"), _txn("t2", account_id="a2")]
    iat = _build_inter_account_transfer(txns, [], {}, "KES")
    assert iat.total is None
    assert iat.pair_count == 0
    assert iat.state == "NO_TRANSFERS_FOUND"


def test_detected_total_is_typed_money_carrying_currency():
    txns = [_txn("o1", account_id="a1"), _txn("i1", account_id="a2")]
    iat = _build_inter_account_transfer(txns, [_link("o1", "i1", 4200)], {}, "KES")
    assert iat.total == Money(4200, "KES")
    assert iat.pairs[0].total == Money(4200, "KES")
    assert iat.pair_count == 1


def test_context_carries_no_markup_or_css():
    txns = [_txn("o1", account_id="a1"), _txn("i1", account_id="a2")]
    iat = _build_inter_account_transfer(txns, [_link("o1", "i1", 4200)], {}, "KES")
    blob = repr(iat)
    for forbidden in ("<", "class=", "#0", "style="):
        assert forbidden not in blob


def test_bank_label_still_importable_from_renderer_namespace():
    """
    _bank_label moved to _snapshot_fetch_helpers.py; the renderer re-imports
    it, so existing callers/tests referencing renderer._bank_label still work.
    """
    from v1.analysis import snapshot_html_renderer as renderer

    assert renderer._bank_label is _bank_label
    assert renderer._bank_label("inline://EQUITY STATEMENT.pdf") == "Equity"
    assert renderer._bank_label("inline://unknown bank.pdf") is None
