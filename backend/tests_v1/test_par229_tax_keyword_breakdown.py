"""
PAR-229 — Tax Compliance Analysis: group by matched keyword/narration
pattern (explicitly NOT tax type).

Pre-check (per the ticket's own requirement, done 2026-09-01 against real
prod data on ifcdbhbuucmjgtjkluna): role_reason values for tax_payment
transactions are clean — exactly the format "keyword_match:{kw}:tax_keywords"
with only 4 distinct keywords actually observed (kra, vat, paye, tax) plus
one null row, no near-duplicate variants needing normalization. This test's
fixture mirrors that real distribution.
"""
from __future__ import annotations

from typing import Any, Dict, List

from v1.analysis.snapshot_context import (
    DEFAULT_TAX_COMPLIANCE_CONFIG,
    TaxKeywordGroup,
    _build_tax_compliance,
    _parse_tax_keyword,
)
from v1.analysis.snapshot_html_renderer import _tax_compliance_ctx_from


def _txn(role: str, signed: int, date: str, role_reason: str | None = None) -> Dict[str, Any]:
    return {
        "role": role, "signed": signed, "abs": abs(signed),
        "txn_date": date, "role_reason": role_reason,
    }


def _always_active(_m: str) -> bool:
    return True


def test_parse_tax_keyword_extracts_from_real_format():
    assert _parse_tax_keyword("keyword_match:vat:tax_keywords") == "vat"
    assert _parse_tax_keyword("keyword_match:kra:tax_keywords") == "kra"
    assert _parse_tax_keyword("keyword_match:paye:tax_keywords") == "paye"


def test_parse_tax_keyword_handles_missing_or_malformed():
    assert _parse_tax_keyword(None) == "(none recorded)"
    assert _parse_tax_keyword("") == "(none recorded)"
    assert _parse_tax_keyword("some_other_reason") == "(none recorded)"


def test_by_keyword_reconciles_with_total_and_is_ranked():
    # Mirrors real prod distribution: kra dominant, vat/paye/tax minority.
    txns = (
        [_txn("tax_payment", -50_000, "2026-01-05", "keyword_match:kra:tax_keywords")] * 10
        + [_txn("tax_payment", -20_000, "2026-02-05", "keyword_match:vat:tax_keywords")] * 3
        + [_txn("tax_payment", -15_000, "2026-03-05", "keyword_match:paye:tax_keywords")] * 2
        + [_txn("tax_payment", -10_000, "2026-04-05", None)]  # legacy/unrecorded row
    )
    tc = _build_tax_compliance(txns, _always_active, DEFAULT_TAX_COMPLIANCE_CONFIG)

    assert tc.by_keyword is not None
    keywords = {g.keyword for g in tc.by_keyword}
    assert keywords == {"kra", "vat", "paye", "(none recorded)"}

    # Ranked descending by total value (kra has the largest total).
    totals = [g.total.cents for g in tc.by_keyword]
    assert totals == sorted(totals, reverse=True)
    assert tc.by_keyword[0].keyword == "kra"

    # Reconciles exactly with the section's own total — same filter, no drift.
    assert sum(g.total.cents for g in tc.by_keyword) == tc.total.cents
    assert sum(g.txn_count for g in tc.by_keyword) == 10 + 3 + 2 + 1


def test_template_never_receives_the_word_tax_type():
    tc = _build_tax_compliance(
        [_txn("tax_payment", -50_000, "2026-01-05", "keyword_match:vat:tax_keywords")],
        _always_active, DEFAULT_TAX_COMPLIANCE_CONFIG,
    )
    ctx = _tax_compliance_ctx_from(tc)
    for row in ctx["by_keyword"]:
        assert "type" not in row["keyword"].lower()
    # The renderer context carries no field or value containing "tax type" —
    # confirms the ticket's hard labeling requirement isn't violated anywhere
    # in what actually reaches the template.
    assert not any("tax type" in str(v).lower() for v in ctx.values())


def test_no_tax_activity_yields_no_keyword_rows():
    tc = _build_tax_compliance(
        [_txn("revenue_operational", 10_000, "2026-01-05")],
        _always_active, DEFAULT_TAX_COMPLIANCE_CONFIG,
    )
    assert tc.by_keyword is None
    ctx = _tax_compliance_ctx_from(tc)
    assert ctx["by_keyword"] == []
