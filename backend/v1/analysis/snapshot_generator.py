"""
Snapshot generator — reconciliation section.

All reconciliation comparisons use FISCAL YEAR dates from pds_audited_financials,
not the ending date of the bank statements.  Statements may extend beyond the
fiscal year (spillover); only the fiscal window is used for comparison.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .reconciliation_engine import (
    _recon_read_cache,
    calculate_account_coverage,
    calculate_cash_position_reconciliation,
    calculate_expense_reconciliation,
    calculate_loan_activity_reconciliation,
    calculate_revenue_reconciliation,
)

logger = logging.getLogger(__name__)

# Tier thresholds
_TIER_HIGH_STATUSES = {"EXACT_MATCH"}
_TIER_MEDIUM_STATUSES = {"EXACT_MATCH", "ACCEPTABLE_VARIANCE", "ACCEPTABLE"}


def generate_reconciliation_section(deal_id: str) -> Dict[str, Any]:
    """
    Build the reconciliation block for a deal snapshot.

    Returns a dict ready for embedding into the snapshot's canonical_json or
    for standalone reporting.
    """
    logger.info("[RECON] Generating reconciliation section for deal %s", deal_id)

    # Share one read cache across all five sub-calculations so the audited
    # financials row and the fiscal-year transaction set are each fetched once
    # per request instead of 4-5 times (the latter is ~12 paginated round-trips).
    cache_token = _recon_read_cache.set({})
    try:
        cash = _safe_call("cash_position", calculate_cash_position_reconciliation, deal_id)
        revenue = _safe_call("revenue", calculate_revenue_reconciliation, deal_id)
        expenses = _safe_call("expenses", calculate_expense_reconciliation, deal_id)
        loans = _safe_call("loan_activity", calculate_loan_activity_reconciliation, deal_id)
        account_coverage = _safe_call("account_coverage", calculate_account_coverage, deal_id)
    finally:
        _recon_read_cache.reset(cache_token)

    tier = _compute_tier(cash, loans, account_coverage)

    reconciliation: Dict[str, Any] = {
        "note": (
            "Cash position compared at fiscal year-end date from audited financials. "
            "Revenue, expense, and loan figures bounded to the same fiscal year window."
        ),
        "tier": tier,
        "cash_position": cash,
        "revenue": revenue,
        "expenses": expenses,
        "loan_activity": loans,
        "account_coverage": account_coverage,
    }

    logger.info(
        "[RECON] Completed — tier=%s cash_status=%s coverage_advisory=%s",
        tier, _status(cash), account_coverage.get("advisory_tier", "UNKNOWN"),
    )
    return reconciliation


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_call(label: str, fn, deal_id: str) -> Dict[str, Any]:
    try:
        return fn(deal_id)
    except ValueError as exc:
        logger.warning("[RECON] %s skipped: %s", label, exc)
        return {"status": "SKIPPED", "reason": str(exc)}
    except Exception as exc:
        logger.exception("[RECON] %s error: %s", label, exc)
        return {"status": "ERROR", "reason": str(exc)}


def _status(section: Dict[str, Any]) -> str:
    return section.get("status") or "UNKNOWN"


def _compute_tier(
    cash: Dict[str, Any],
    loans: Dict[str, Any],
    account_coverage: Optional[Dict[str, Any]] = None,
) -> str:
    cash_status = _status(cash)
    loan_status = _status(loans)

    if cash_status in _TIER_HIGH_STATUSES and loan_status in _TIER_HIGH_STATUSES:
        base_tier = "HIGH_CONFIDENCE"
    elif cash_status in _TIER_MEDIUM_STATUSES and loan_status in _TIER_MEDIUM_STATUSES:
        base_tier = "MEDIUM_CONFIDENCE"
    else:
        base_tier = "LOW_CONFIDENCE"

    # CRITICAL account gaps (>15% of declared cash missing) block HIGH_CONFIDENCE.
    # MINOR / MATERIAL / NEGLIGIBLE are advisory only — no score penalty.
    if (
        base_tier == "HIGH_CONFIDENCE"
        and account_coverage
        and account_coverage.get("advisory_tier") == "CRITICAL"
    ):
        logger.info(
            "[RECON] HIGH_CONFIDENCE blocked — account_coverage advisory=CRITICAL "
            "missing_pct=%.1f%%", account_coverage.get("missing_pct", 0)
        )
        return "MEDIUM_CONFIDENCE"

    return base_tier
