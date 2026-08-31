"""
PAR-207 — gap-waterfall breakdown on the Cash Position and Revenue rows.

Verification follows PAR-189/PAR-116 precedent: drive the REAL
_build_four_point_reconciliation() / _four_point_recon_ctx_from() production
functions with REAL prod values, not synthetic mocks.

All figures below were computed by replicating the production algorithms in SQL
against the live Supabase project (ifcdbhbuucmjgtjkluna) on 2026-08-31 and
cross-checked against PAR-207's own correctness check:

  Buildex (4f4f4cba-d688-4b9c-a887-71a0dd6b83d5), FY2025
    cash: KCB net movement 59,174,705c + Equity 155,827,242c = 215,001,947c
          vs declared 212,578,100c -> +2,423,847c = +1.14%   (matches PAR-207)
    coverage: MATERIAL, 87.47%, 2 of 4 accounts submitted (KCB, Equity)

Two structural facts this suite pins, both re-verified against live prod
2026-08-31 and both DISCLOSED rather than fixed (PAR-207 says disclose, don't
fix):

  1. balance_cents is NULL on all 193,327 rows of pds_raw_transactions, so
     calculate_cash_position_reconciliation()'s "balance_column" primary path
     is dead code and every deal runs "flow_derived". The observed figure is a
     fiscal-year NET MOVEMENT, not a closing balance.
  2. 0 transactions carry a transfer/internal_transfer role, 0 rows exist in
     pds_transfer_links, and 0 deals have >1 distinct account_id -> transfer
     detection resolves UNAVAILABLE for every deal in the system (PAR-102), so
     the Revenue disclosure must render universally, not per-deal.
"""
import os
import sys

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest

from backend.v1.analysis.snapshot_context import (
    _build_four_point_reconciliation,
    DEFAULT_RECON_CHECK_CONFIG,
)
from backend.v1.analysis.snapshot_html_renderer import _four_point_recon_ctx_from

# ── real prod fixture values ────────────────────────────────────────────────
_AF = {
    "financial_year": 2025,
    "cash_and_equivalents_cents": 212578100,
    "turnover_cents": 37206227700,
    "trade_receivables_cents": 563654800,
    "other_receivables_cents": 0,
}
_CASH_BREAKDOWN = {"KCB": 30312500, "Absa": 23539700, "Zemo": 3107600, "Equity": 155618200}
_BUILDEX_SUBMITTED = {"KCB", "Equity"}
_BUILDEX_BANK_BALANCES = [
    ("KCB STATEMENT 01.01.2025 TO 31.12.2025 (2).pdf", 59174705),
    ("EQUITY BANK STATEMENT 01.01.2025 TO 31.12.2025 (2).pdf", 155827242),
]
_BUILDEX_TOTAL_BANK_CENTS = 215001947
_OBSERVED_REVENUE_KES = 286796695.35


def _acct_cov(submitted=_BUILDEX_SUBMITTED, coverage_pct=87.47, advisory="MATERIAL"):
    details, missing_cents = [], 0
    for bank, cents in _CASH_BREAKDOWN.items():
        status = "SUBMITTED" if bank in submitted else "MISSING"
        if status == "MISSING":
            missing_cents += cents
        details.append({
            "bank_name": bank, "declared_balance_cents": cents, "status": status,
        })
    return {
        "coverage_pct": coverage_pct, "advisory_tier": advisory,
        "declared_accounts_count": len(_CASH_BREAKDOWN),
        "submitted_accounts_count": len(submitted),
        "missing_accounts_count": len(_CASH_BREAKDOWN) - len(submitted),
        "missing_balance_cents": missing_cents,
        "account_details": details,
    }


def _section(bank_balances=None, total_bank_cents=_BUILDEX_TOTAL_BANK_CENTS,
             include_cash_detail=True):
    bank_balances = _BUILDEX_BANK_BALANCES if bank_balances is None else bank_balances
    declared_total = _AF["cash_and_equivalents_cents"]
    variance = total_bank_cents - declared_total
    declared_rev = round(_AF["turnover_cents"] / 100, 2)
    cash = {
        "status": "ACCEPTABLE_VARIANCE", "method": "flow_derived",
        "variance_pct": round(variance / declared_total * 100, 2),
        "variance_kes": round(variance / 100, 2),
        "total_bank_kes": round(total_bank_cents / 100, 2),
        "total_declared_kes": round(declared_total / 100, 2),
    }
    if include_cash_detail:
        cash["declared_balances"] = [
            {"account": k, "balance_kes": round(v / 100, 2), "balance_cents": v}
            for k, v in _CASH_BREAKDOWN.items()
        ]
        cash["bank_balances"] = [
            {"source": s, "balance_kes": round(c / 100, 2), "balance_cents": c,
             "date": "2025-12-31", "method": "flow_derived"}
            for s, c in bank_balances
        ]
    return {
        "cash_position": cash,
        "revenue": {
            "fiscal_period": "2025-01-01 to 2025-12-31",
            "bank_inflows_kes": _OBSERVED_REVENUE_KES,
            "declared_revenue_kes": declared_rev,
            "gap_kes": round(declared_rev - _OBSERVED_REVENUE_KES, 2),
            "gap_pct": round((declared_rev - _OBSERVED_REVENUE_KES) / declared_rev * 100, 2),
            "assessment": "RISK — revenue gap too large (>15%)",
        },
        "expenses": {"gap_pct": 18.15, "explanation": "Gap explained by: non-cash expenses",
                      "bank_outflows_kes": 297715131.98, "declared_expenses_kes": 363732091.00},
        "loan_activity": {"status": "VARIANCE", "variance_pct": -236.7,
                           "bank_net_borrowing_kes": -3495696.00,
                           "declared_net_borrowing_kes": 2557092.00},
    }


def _rows(section=None, cov=None, af=None, transfer_state="UNAVAILABLE"):
    section = section if section is not None else _section()
    cov = cov if cov is not None else _acct_cov()
    missing = [a["bank_name"] for a in cov.get("account_details", [])
               if a["status"] != "SUBMITTED"]
    fpr = _build_four_point_reconciliation(
        section, True, bool(missing),
        f"Coverage gap — {', '.join(missing)} not submitted." if missing else "",
        "2025", "KES", DEFAULT_RECON_CHECK_CONFIG,
        acct_cov_raw=cov, af=_AF if af is None else af, transfer_state=transfer_state,
    )
    ctx = _four_point_recon_ctx_from(fpr)
    return {r["check"]: r for r in ctx["recon_rows"]}


# ── scope: only Cash Position and Revenue get waterfalls ────────────────────

def test_only_cash_position_and_revenue_carry_waterfalls():
    rows = _rows()
    assert rows["Revenue"]["waterfall"] is not None
    assert rows["Cash position"]["waterfall"] is not None
    # Expenses is untouched by PAR-207; Loan activity is deliberately excluded
    # until PAR-211's Parity Science scoping resolves.
    assert rows["Expenses"]["waterfall"] is None
    assert rows["Loan activity"]["waterfall"] is None


def test_loan_activity_has_no_waterfall_even_with_full_inputs():
    """Guards the PAR-211 block specifically: it must not appear by accident."""
    rows = _rows()
    assert rows["Loan activity"]["waterfall"] is None


# ── Cash Position ───────────────────────────────────────────────────────────

def _labels(wf):
    return [c["label"] for c in wf["components"]]


def test_cash_waterfall_splits_every_declared_account_with_submission_status():
    wf = _rows()["Cash position"]["waterfall"]
    by_label = {c["label"]: c for c in wf["components"]}
    for bank in _CASH_BREAKDOWN:
        assert bank in by_label, f"declared account {bank} missing from waterfall"
    assert by_label["KCB"]["sub"] == "statement submitted"
    assert by_label["Equity"]["sub"] == "statement submitted"
    assert by_label["Absa"]["sub"] == "no statement submitted"
    assert by_label["Zemo"]["sub"] == "no statement submitted"


def test_cash_waterfall_observed_matches_flow_derived_path_not_idealised_balance():
    """
    The observed figures must be exactly what the flow-derived path computes
    today (per-statement fiscal-year net movement), NOT silently corrected to
    what the dead balance_column path 'should' produce — that correction is a
    different, unscoped change.
    """
    wf = _rows()["Cash position"]["waterfall"]
    by_label = {c["label"]: c for c in wf["components"]}
    assert by_label["KCB STATEMENT 01.01.2025 TO 31.12.2025 (2).pdf"]["amount_str"] == "KES 591,747"
    assert by_label["EQUITY BANK STATEMENT 01.01.2025 TO 31.12.2025 (2).pdf"]["amount_str"] == "KES 1,558,272"
    assert by_label["Observed total"]["amount_str"] == "KES 2,150,019"
    assert by_label["Declared total"]["amount_str"] == "KES 2,125,781"
    # every observed line is labelled as a net movement, not a balance
    for src, _ in _BUILDEX_BANK_BALANCES:
        assert by_label[src]["sub"] == "fiscal-year net movement"


def test_cash_waterfall_attributes_missing_accounts_as_their_own_amount():
    wf = _rows()["Cash position"]["waterfall"]
    comp = next(c for c in wf["components"]
                if c["label"].startswith("Declared balance in accounts with no statement"))
    # Absa 23,539,700c + Zemo 3,107,600c = 26,647,300c
    assert comp["amount_str"] == "KES 266,473"
    assert "2 of 4 declared accounts" in comp["sub"]


def test_cash_waterfall_discloses_flow_derived_method():
    wf = _rows()["Cash position"]["waterfall"]
    joined = " ".join(wf["disclosures"])
    assert "net movement" in joined and "closing balance" in joined


def test_cash_waterfall_discloses_declared_component_drift():
    """
    Real Buildex data: per-account cash_breakdown sums to KES 2,125,780 while
    the declared cash-and-equivalents total is KES 2,125,781. The block must
    state that difference rather than show lines that visibly do not sum.
    """
    wf = _rows()["Cash position"]["waterfall"]
    joined = " ".join(wf["disclosures"])
    assert "KES 2,125,780" in joined and "KES 2,125,781" in joined
    assert "difference of KES 1" in joined


def test_cash_waterfall_omitted_when_sealed_snapshot_lacks_per_account_fields():
    """Older sealed snapshots predate declared_balances/bank_balances."""
    rows = _rows(section=_section(include_cash_detail=False))
    assert rows["Cash position"]["waterfall"] is None


def test_cash_waterfall_has_no_missing_account_line_when_coverage_is_complete():
    cov = _acct_cov(submitted=set(_CASH_BREAKDOWN), coverage_pct=100.0, advisory="NEGLIGIBLE")
    wf = _rows(cov=cov)["Cash position"]["waterfall"]
    assert not any(c["label"].startswith("Declared balance in accounts with no statement")
                   for c in wf["components"])
    assert all("cannot contribute to the observed total" not in d for d in wf["disclosures"])


def test_cash_waterfall_survives_missing_account_coverage():
    """calculate_account_coverage can return SKIPPED with no account_details."""
    wf = _rows(cov={"status": "SKIPPED", "reason": "No cash_breakdown"})["Cash position"]["waterfall"]
    assert wf is not None
    # declared accounts still listed, just with no submitted/missing qualifier
    assert "KCB" in _labels(wf)
    assert all(c["sub"] == "" for c in wf["components"] if c["label"] in _CASH_BREAKDOWN)


# ── Revenue ─────────────────────────────────────────────────────────────────

def test_revenue_waterfall_states_declared_observed_and_gap():
    wf = _rows()["Revenue"]["waterfall"]
    by_label = {c["label"]: c for c in wf["components"]}
    assert by_label["Declared turnover"]["amount_str"] == "KES 372,062,277"
    assert by_label["Observed operational inflows"]["amount_str"] == "KES 286,796,695"
    assert by_label["Declared less observed"]["amount_str"] == "KES 85,265,582"


def test_revenue_waterfall_includes_accrual_timing_components():
    wf = _rows()["Revenue"]["waterfall"]
    by_label = {c["label"]: c for c in wf["components"]}
    assert by_label["Trade receivables outstanding at year-end"]["amount_str"] == "KES 5,636,548"
    # other_receivables_cents is 0 on this deal -> omitted rather than shown as zero
    assert "Other receivables at year-end" not in by_label


def test_revenue_waterfall_discloses_par102_transfer_gap():
    wf = _rows()["Revenue"]["waterfall"]
    joined = " ".join(wf["disclosures"])
    assert "PAR-102" in joined
    assert "not net of inter-account transfers" in joined


@pytest.mark.parametrize("state", ["UNAVAILABLE", "DETECTED", "NO_TRANSFERS_FOUND"])
def test_revenue_waterfall_always_discloses_transfer_state(state):
    """
    The disclosure is driven off the deal's real detection state so it stays
    accurate if PAR-102 is ever fixed — but some transfer statement always
    renders, never silence.
    """
    wf = _rows(transfer_state=state)["Revenue"]["waterfall"]
    assert len(wf["disclosures"]) == 1
    if state == "UNAVAILABLE":
        assert "PAR-102" in wf["disclosures"][0]
    else:
        assert "PAR-102" not in wf["disclosures"][0]


# ── PAR-150 boundary ────────────────────────────────────────────────────────

_VERDICT_WORDS = [
    "healthy", "unhealthy", "expected", "unexpected", "concerning", "concern",
    "risk", "risky", "good", "bad", "poor", "strong", "weak", "acceptable",
    "unacceptable", "suspicious", "normal", "abnormal", "favourable", "favorable",
    "reasonable", "unreasonable", "material weakness", "red flag",
]


def test_no_waterfall_text_carries_a_verdict():
    """
    PAR-150 Rule 4 / PAR-206's identical boundary: components and amounts only.
    No line may evaluate whether a figure is good or bad for this deal.
    """
    rows = _rows()
    for check in ("Revenue", "Cash position"):
        wf = rows[check]["waterfall"]
        blob = " ".join(
            [c["label"] for c in wf["components"]]
            + [c["sub"] for c in wf["components"]]
            + wf["disclosures"]
        ).lower()
        for word in _VERDICT_WORDS:
            assert word not in blob, f"{check} waterfall carries verdict word {word!r}"
