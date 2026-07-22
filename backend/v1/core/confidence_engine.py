from math import floor
from typing import Dict, List

# Weight in basis points (no float in v1 core). Production: 0, 0.5, 1.0. Tests: 0.1, 0.6, 0.7, 0.8, 0.9.
_WEIGHT_STR_TO_BP = {
    "0": 0, "0.0": 0,
    "0.1": 1000, "0.5": 5000, "0.6": 6000, "0.7": 7000,
    "0.8": 8000, "0.9": 9000, "1.0": 10000,
}


def _weight_to_bp(weight) -> int:
    """Convert API weight (0, 0.5, 1.0) to basis points without float."""
    return _WEIGHT_STR_TO_BP.get(str(weight), 0)


def compute_override_penalty_bp(overrides: List[Dict], entity_values: Dict[str, int], non_transfer_abs_total: int) -> int:
    if non_transfer_abs_total <= 0:
        return 0
    latest_per_entity = {}
    for ov in sorted(overrides, key=lambda o: o.get("created_at", ""), reverse=True):
        key = ov.get("entity_id")
        if key and key not in latest_per_entity:
            latest_per_entity[key] = ov

    impact_bp = 0
    for entity_id, ov in latest_per_entity.items():
        val = abs(int(entity_values.get(entity_id, 0)))
        if val == 0:
            continue
        weight_bp = _weight_to_bp(ov.get("weight", 0))
        # Integer arithmetic: (val * 10000 // total) * weight_bp // 10000
        contrib_bp = (val * 10000 // non_transfer_abs_total) * weight_bp // 10000
        impact_bp += contrib_bp
    penalty_bp = min(impact_bp, 7000)
    return penalty_bp


def compute_tier(confidence_bp: int, reconciliation_status: str) -> (str, bool):
    tier = "Low"
    if confidence_bp >= 8500:
        tier = "High"
    elif confidence_bp >= 7000:
        tier = "Medium"
    capped = False
    if reconciliation_status != "OK" and tier == "High":
        tier = "Medium"
        capped = True
    return tier, capped


def compute_coverage_tier(confidence_bp: int) -> str:
    """
    PAR-47: the same Low/Medium/High thresholds as compute_tier(), but as a
    pure function of confidence_bp alone — no reconciliation_status gating.
    compute_tier() caps High->Medium whenever reconciliation isn't OK, which
    today is every deal (no deal has accrual data yet), so `tier` reads as
    "this deal is weak" when the truth is "no deal can score High right now,
    for a reason unrelated to this deal's own data completeness". Additive:
    does not change compute_tier()/finalize_confidence()'s existing behavior.
    """
    if confidence_bp >= 8500:
        return "High"
    if confidence_bp >= 7000:
        return "Medium"
    return "Low"


def finalize_confidence(base_after_months_bp: int, override_penalty_bp: int, reconciliation_status: str) -> Dict:
    final_conf = max(0, base_after_months_bp - override_penalty_bp)
    tier, capped = compute_tier(final_conf, reconciliation_status)
    return {
        "final_confidence_bp": final_conf,
        "tier": tier,
        "tier_capped": capped,
        "coverage_tier": compute_coverage_tier(final_conf),
        "override_penalty_bp": override_penalty_bp,
    }
