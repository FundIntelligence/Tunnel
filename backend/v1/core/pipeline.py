import uuid
from typing import Dict, List, Tuple

from ..config import SCHEMA_VERSION, CONFIG_VERSION
from ..parsing.common import canonical_hash
from .transfer_matcher import match_transfers
from .entities import build_entities
from .classifier import classify
from .anomaly_detector import annotate_anomalies
from .metrics_engine import compute_metrics
from .confidence_engine import compute_override_penalty_bp, finalize_confidence


def run_pipeline(
    *,
    deal_id: str,
    raw_transactions: List[Dict],
    overrides: List[Dict],
    accrual: Dict,
) -> Tuple[Dict, List[Dict], List[Dict], List[Dict]]:
    """
    Returns (analysis_run, transfer_links, entities, txn_entity_records)
    txn_entity_records: list of {txn_id, entity_id, role, role_version}
    """
    # Step 1: transfer matching
    txs, transfer_links = match_transfers(raw_transactions)

    # Step 2: entities
    entities, txn_entity_map, entities_hash = build_entities(deal_id, txs)

    # Step 3: classify
    txn_entity_records = []
    for tx in txs:
        role = classify(tx)
        tx["role"] = role
        txn_entity_records.append(
            {
                "deal_id": deal_id,
                "txn_id": tx["txn_id"],
                "entity_id": txn_entity_map[tx["txn_id"]],
                "role": role,
                "role_version": "v1_rules",
            }
        )

    # Step 3.5: anomaly detection — annotates each tx["anomalies"] in-place
    entity_id_to_display = {e["entity_id"]: e["display_name"] for e in entities}
    entity_display_map = {tid: entity_id_to_display[eid] for tid, eid in txn_entity_map.items()}
    annotate_anomalies(txs, entity_display_map)

    # Step 4: metrics
    metrics = compute_metrics(txs, accrual)

    # Step 5: overrides impact (entity_abs_value per entity)
    entity_values = {}
    for tx in txs:
        eid = txn_entity_map[tx["txn_id"]]
        entity_values[eid] = entity_values.get(eid, 0) + abs(int(tx["signed_amount_cents"]))
    override_penalty_bp = compute_override_penalty_bp(overrides, entity_values, metrics["non_transfer_abs_total_cents"])
    confidence = finalize_confidence(metrics["base_after_months_bp"], override_penalty_bp, metrics["reconciliation_status"])

    transfer_links_hash = canonical_hash(sorted(transfer_links, key=lambda l: (l.get("txn_out_id") or "", l.get("txn_in_id") or "")))
    overrides_hash = canonical_hash(sorted(overrides, key=lambda o: o.get("id") or ""))

    analysis_run = {
        "id": str(uuid.uuid4()),
        "deal_id": deal_id,
        "state": "LIVE_DRAFT",
        "schema_version": SCHEMA_VERSION,
        "config_version": CONFIG_VERSION,
        "run_trigger": "parse_complete",
        "non_transfer_abs_total_cents": metrics["non_transfer_abs_total_cents"],
        "classified_abs_total_cents": metrics["classified_abs_total_cents"],
        "coverage_pct_bp": metrics["coverage_bp"],
        "missing_month_count": metrics["missing_month_count"],
        "missing_month_penalty_bp": metrics["missing_month_penalty_bp"],
        "override_penalty_bp": override_penalty_bp,
        "reconciliation_status": metrics["reconciliation_status"],
        "reconciliation_state": metrics["reconciliation_state"],
        "reconciliation_pct_bp": metrics["reconciliation_bp"],
        "base_confidence_bp": metrics["base_confidence_bp"],
        "final_confidence_bp": confidence["final_confidence_bp"],
        "tier": confidence["tier"],
        "tier_capped": confidence["tier_capped"],
        "coverage_tier": confidence["coverage_tier"],
        "raw_transaction_hash": canonical_hash(sorted(txs, key=lambda t: t["txn_id"])),
        "transfer_links_hash": transfer_links_hash,
        "entities_hash": entities_hash,
        "overrides_hash": overrides_hash,
        "bank_operational_inflow_cents": metrics.get("bank_operational_inflow_cents", 0),
    }

    return analysis_run, transfer_links, entities, txn_entity_records
