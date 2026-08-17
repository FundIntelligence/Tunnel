from datetime import datetime
from typing import Dict, List, Tuple


def _active_period_dates(transactions: List[Dict]) -> Tuple[str, str]:
    dates = [t["txn_date"] for t in transactions] or []
    return (min(dates), max(dates)) if dates else (None, None)


def _missing_months(txn_dates: List[str]) -> int:
    """Count interior months (strictly between first and last transaction month)
    that have NO transactions. A dataset with continuous data returns 0."""
    if not txn_dates:
        return 0
    dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in txn_dates)
    months_with_data = {(d.year, d.month) for d in dates}
    start, end = dates[0], dates[-1]
    # Build set of all interior months (strictly between start and end month)
    expected_interior: set = set()
    cur = _add_months(start.replace(day=1), 1)
    while (cur.year, cur.month) < (end.year, end.month):
        expected_interior.add((cur.year, cur.month))
        cur = _add_months(cur, 1)
    return len(expected_interior - months_with_data)


def _add_months(dt, months):
    year = dt.year + (dt.month + months - 1) // 12
    month = (dt.month + months - 1) % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


def _parse_txn_date(txn_date: str):
    if not txn_date:
        return None
    try:
        return datetime.strptime(txn_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _tag_reversal_pairs(transactions: List[Dict], window_days: int = 30) -> set:
    """
    Post-classification pass:
    - Finds reversal txns and matches them to opposite-direction txns with same abs amount
      within the configured date window.
    - Marks both sides as zero-net reversal pair.
    Returns a set of txn_id values that are part of matched pairs.
    """
    reversal_roles = frozenset({"reversal_credit", "reversal_debit"})
    excluded_txn_ids = set()

    # Reset tags for deterministic reruns.
    for tx in transactions:
        tx["is_reversal_pair_zero_net"] = False
        tx["reversal_pair_id"] = None

    used_candidate_indices = set()
    reversals = []
    for idx, tx in enumerate(transactions):
        if tx.get("role") in reversal_roles and not tx.get("is_transfer"):
            reversals.append((idx, tx))

    # Stable ordering ensures deterministic pairing.
    reversals.sort(key=lambda item: ((item[1].get("txn_date") or ""), (item[1].get("txn_id") or ""), item[0]))

    pair_seq = 0
    for rev_idx, rev_tx in reversals:
        rev_amt = int(rev_tx.get("signed_amount_cents", 0))
        rev_abs = abs(rev_amt)
        if rev_abs == 0:
            continue

        rev_date = _parse_txn_date(rev_tx.get("txn_date"))
        best_idx = None
        best_gap = None

        for cand_idx, cand_tx in enumerate(transactions):
            if cand_idx == rev_idx or cand_idx in used_candidate_indices:
                continue
            if cand_tx.get("is_transfer"):
                continue
            cand_amt = int(cand_tx.get("signed_amount_cents", 0))
            if abs(cand_amt) != rev_abs:
                continue
            if cand_amt == 0 or (cand_amt > 0) == (rev_amt > 0):
                continue

            cand_date = _parse_txn_date(cand_tx.get("txn_date"))
            if rev_date is not None and cand_date is not None:
                day_gap = abs((rev_date - cand_date).days)
                if day_gap > window_days:
                    continue
            else:
                # Keep date-less candidates as lowest preference.
                day_gap = window_days + 1

            if best_gap is None or day_gap < best_gap or (day_gap == best_gap and cand_idx < best_idx):
                best_gap = day_gap
                best_idx = cand_idx

        if best_idx is None:
            continue

        pair_seq += 1
        pair_id = f"rev_pair_{pair_seq}"
        candidate = transactions[best_idx]
        rev_tx["is_reversal_pair_zero_net"] = True
        rev_tx["reversal_pair_id"] = pair_id
        candidate["is_reversal_pair_zero_net"] = True
        candidate["reversal_pair_id"] = pair_id
        used_candidate_indices.add(best_idx)

        rev_txn_id = rev_tx.get("txn_id")
        if rev_txn_id:
            excluded_txn_ids.add(rev_txn_id)
        cand_txn_id = candidate.get("txn_id")
        if cand_txn_id:
            excluded_txn_ids.add(cand_txn_id)

    return excluded_txn_ids


def compute_metrics(transactions: List[Dict], accrual: Dict) -> Dict:
    """
    transactions: list with fields txn_date (YYYY-MM-DD), signed_amount_cents, abs_amount_cents, is_transfer, role
    accrual: dict with keys accrual_revenue_cents, accrual_period_start, accrual_period_end
    Returns metrics dict and component hashes.
    """
    matched_reversal_pair_txn_ids = _tag_reversal_pairs(transactions)
    non_transfer = [t for t in transactions if not t.get("is_transfer")]
    non_transfer_abs_total = sum(abs(int(t["signed_amount_cents"])) for t in non_transfer)
    classified_abs_total = sum(abs(int(t["signed_amount_cents"])) for t in non_transfer if t.get("role") != "other")

    if non_transfer_abs_total == 0:
        return {
            "non_transfer_abs_total_cents": 0,
            "classified_abs_total_cents": 0,
            "coverage_bp": 0,
            "missing_month_count": 0,
            "missing_month_penalty_bp": 0,
            "reconciliation_status": "NOT_RUN",
            # PAR-47: reconciliation_status collapses several distinct reasons into
            # "NOT_RUN". reconciliation_state is the same underlying branch,
            # honestly named — additive, does not change reconciliation_status.
            "reconciliation_state": "NO_TRANSACTION_DATA",
            "reconciliation_bp": None,
            "base_confidence_bp": 0,
            "base_after_months_bp": 0,
            "coverage_bp_raw": 0,
            "bank_operational_inflow_cents": 0,
        }

    coverage_bp = classified_abs_total * 10000 // non_transfer_abs_total

    _OPERATIONAL_INFLOW_ROLES = frozenset({"revenue_operational", "mpesa_inflow"})
    bank_operational_inflow_cents = sum(
        int(t["signed_amount_cents"])
        for t in non_transfer
        if int(t["signed_amount_cents"]) > 0
        and t.get("role") in _OPERATIONAL_INFLOW_ROLES
        and t.get("txn_id") not in matched_reversal_pair_txn_ids
    )

    missing_month_count = _missing_months([t["txn_date"] for t in transactions])
    missing_month_penalty_bp = min(missing_month_count * 1000, 5000)

    recon_status = "NOT_RUN"
    # PAR-47: reconciliation_state is the same branch logic as recon_status
    # below, purely reclassified into five honest reasons instead of
    # collapsing three of them into "NOT_RUN". Additive — recon_status keeps
    # its exact current values/meaning for existing consumers.
    recon_state = "PENDING_ACCRUAL_DATA"
    recon_bp = None
    accrual_revenue_cents = accrual.get("accrual_revenue_cents")
    accrual_start = accrual.get("accrual_period_start")
    accrual_end = accrual.get("accrual_period_end")

    if accrual_revenue_cents and accrual_revenue_cents > 0 and accrual_start and accrual_end:
        # overlap check
        start, end = _active_period_dates(transactions)
        if not start or not end:
            recon_status = "NOT_RUN"
            recon_state = "FAILED_OVERLAP"  # active period undeterminable — can't establish overlap
        else:
            active_start = datetime.strptime(start, "%Y-%m-%d").date()
            active_end = datetime.strptime(end, "%Y-%m-%d").date()
            accr_start = datetime.strptime(accrual_start, "%Y-%m-%d").date()
            accr_end = datetime.strptime(accrual_end, "%Y-%m-%d").date()
            overlap_days = max(
                0,
                (min(active_end, accr_end) - max(active_start, accr_start)).days + 1,
            )
            accrual_days = (accr_end - accr_start).days + 1
            if accrual_days <= 0:
                recon_status = "FAILED_OVERLAP"
                recon_state = "FAILED_OVERLAP"
            else:
                # 60% threshold in basis points (no float in v1 core)
                overlap_bp = (overlap_days * 10000 // accrual_days) if accrual_days else 0
                if overlap_bp < 6000:
                    recon_status = "FAILED_OVERLAP"
                    recon_state = "FAILED_OVERLAP"
                else:
                    if bank_operational_inflow_cents <= 0:
                        recon_status = "NOT_RUN"
                        recon_state = "FAILED_ZERO_INFLOW"
                    else:
                        diff = abs(accrual_revenue_cents - bank_operational_inflow_cents)
                        recon_bp = max(0, 10000 - (diff * 10000 // accrual_revenue_cents))
                        recon_status = "OK"
                        recon_state = "OK"

    base_confidence = coverage_bp if recon_status != "OK" or recon_bp is None else min(coverage_bp, recon_bp)
    base_after_months = max(0, base_confidence - missing_month_penalty_bp)

    return {
        "non_transfer_abs_total_cents": non_transfer_abs_total,
        "classified_abs_total_cents": classified_abs_total,
        "coverage_bp": coverage_bp,
        "missing_month_count": missing_month_count,
        "missing_month_penalty_bp": missing_month_penalty_bp,
        "reconciliation_status": recon_status,
        "reconciliation_state": recon_state,
        "reconciliation_bp": recon_bp,
        "base_confidence_bp": base_confidence,
        "base_after_months_bp": base_after_months,
        "bank_operational_inflow_cents": bank_operational_inflow_cents,
    }
