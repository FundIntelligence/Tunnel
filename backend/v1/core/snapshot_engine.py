import base64
import gzip
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..parsing.common import canonical_hash, sort_rows
from .declared_financials import DeclaredFinancials
from .reconciliation import compute_reconciliation

logger = logging.getLogger(__name__)

# Above this size, canonical JSON is gzip+base64 prefixed before persisting so PostgREST
# INSERT requests stay under typical ~1–8 MiB body limits for large deals.
CANONICAL_JSON_COMPRESS_MIN_LEN = 262_144  # 256 KiB

_GZIP_PREFIX = "__PDS1_GZIP_B64__:"


def compress_canonical_json_if_large(plain: str) -> str:
    if len(plain) < CANONICAL_JSON_COMPRESS_MIN_LEN:
        return plain
    raw = gzip.compress(plain.encode("utf-8"), compresslevel=6)
    enc = _GZIP_PREFIX + base64.b64encode(raw).decode("ascii")
    logger.info(
        "[SNAPSHOT] canonical_json compressed %d -> %d bytes",
        len(plain),
        len(enc),
    )
    return enc


def decompress_canonical_json_if_needed(stored: str) -> str:
    if not stored:
        return stored
    if stored.startswith(_GZIP_PREFIX):
        raw = base64.b64decode(stored[len(_GZIP_PREFIX) :].encode("ascii"))
        return gzip.decompress(raw).decode("utf-8")
    return stored


def decode_snapshot_row(snapshot: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Expand stored canonical_json to plain JSON text for API / pipeline consumers."""
    if not snapshot:
        return None
    out = dict(snapshot)
    cj = out.get("canonical_json")
    if isinstance(cj, str):
        out["canonical_json"] = decompress_canonical_json_if_needed(cj)
    return out


def _build_financial_state_payload(
    *,
    schema_version: str,
    config_version: str,
    deal_id: str,
    currency: str,
    transactions: List[Dict[str, Any]],
    transfer_links: List[Dict[str, Any]],
    entities: List[Dict[str, Any]],
    txn_entity_map: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    confidence: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Outcome-only view of a snapshot (excludes override audit trail and snapshot metadata).
    This is the canonical input to financial_state_hash.
    """
    return {
        "schema_version": schema_version,
        "config_version": config_version,
        "deal_id": deal_id,
        "currency": currency,
        "raw_transaction_hash": canonical_hash(transactions),
        "transactions": transactions,
        "transfer_links": transfer_links,
        "entities": entities,
        "txn_entity_map": txn_entity_map,
        "metrics": metrics,
        "confidence": confidence,
    }


def compute_financial_state_hash(payload: Dict[str, Any]) -> str:
    """
    Deterministically compute the financial_state_hash from a payload (already sorted).
    Expects the payload to include the same keys produced by _build_financial_state_payload.
    """
    return canonical_hash([payload])


def compute_financial_state_hash_from_canonical_json(canonical_json: str) -> str:
    """
    Idempotent helper for backfill: parses stored canonical_json, rebuilds the
    outcome-only view, and returns the financial_state_hash.
    """
    data = json.loads(decompress_canonical_json_if_needed(canonical_json))
    # Re-sort defensively to avoid relying on stored order
    transactions = sort_rows(data.get("transactions", []))
    transfer_links = sorted(
        data.get("transfer_links", []),
        key=lambda l: (l.get("txn_out_id") or "", l.get("txn_in_id") or ""),
    )
    entities = sorted(data.get("entities", []), key=lambda e: e["entity_id"])
    txn_entity_map = sorted(data.get("txn_entity_map", []), key=lambda m: m["txn_id"])
    metrics = data.get("metrics", {})
    confidence = data.get("confidence", {})

    fs_payload = _build_financial_state_payload(
        schema_version=data.get("schema_version"),
        config_version=data.get("config_version"),
        deal_id=data.get("deal_id"),
        currency=data.get("currency"),
        transactions=transactions,
        transfer_links=transfer_links,
        entities=entities,
        txn_entity_map=txn_entity_map,
        metrics=metrics,
        confidence=confidence,
    )
    return compute_financial_state_hash(fs_payload)


def build_pds_payload(
    *,
    schema_version: str,
    config_version: str,
    deal_id: str,
    currency: str,
    raw_transactions: List[Dict[str, Any]],
    transfer_links: List[Dict[str, Any]],
    entities: List[Dict[str, Any]],
    txn_entity_map: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    confidence: Dict[str, Any],
    overrides_applied: List[Dict[str, Any]],
    audited_financials: Optional[Dict[str, Any]] = None,
    recon_section: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    sorted_txns = sorted(
        raw_transactions,
        key=lambda r: (
            r["txn_date"],
            r["account_id"],
            r["signed_amount_cents"],
            r["normalized_descriptor"],
            r["txn_id"],
        ),
    )

    # TEMP: declared revenue placeholder (manual input for now)
    declared = DeclaredFinancials(
        revenue=[0],  # replace later with real input
        period="annual",
    )
    reconciliation = compute_reconciliation(
        declared=declared,
        transactions=sorted_txns,
    )
    rev = reconciliation.get("revenue", {}) if isinstance(reconciliation, dict) else {}
    detected = rev.get("detected_cents", 0)
    declared_cents = rev.get("declared_cents", 0)
    delta_bps = rev.get("delta_bps")
    status = rev.get("status")

    # convert bps to percentage (integer)
    if delta_bps is None:
        delta_pct = None
    else:
        delta_pct = int(delta_bps / 100)

    if status == "MATCH":
        recommendation = "Financials are consistent with bank activity"
    elif status == "NEEDS_REVIEW":
        recommendation = "Minor inconsistencies detected — review recommended"
    elif status == "MISMATCH":
        recommendation = "Significant discrepancy — investigate revenue validity"
    elif status == "INSUFFICIENT_DATA":
        recommendation = "Declared financials required for verification"
    else:
        recommendation = "Unable to determine"

    reconciliation_summary = {
        "status": status,
        "detected_revenue": detected,
        "declared_revenue": declared_cents,
        "delta_pct": delta_pct,
        "insight": rev.get("insight"),
        "recommendation": recommendation,
    }
    sorted_transfer_links = sorted(
        transfer_links,
        key=lambda l: (l.get("txn_out_id") or "", l.get("txn_in_id") or ""),
    )
    sorted_entities = sorted(entities, key=lambda e: e["entity_id"])
    sorted_txn_entity_map = sorted(txn_entity_map, key=lambda m: m["txn_id"])

    metrics_block = {
        "coverage_bp": metrics.get("coverage_bp"),
        "missing_month_count": metrics.get("missing_month_count"),
        "missing_month_penalty_bp": metrics.get("missing_month_penalty_bp"),
        "reconciliation_status": metrics.get("reconciliation_status"),
        "reconciliation_bp": metrics.get("reconciliation_bp"),
    }
    confidence_block = {
        "final_confidence_bp": confidence.get("final_confidence_bp"),
        "tier": confidence.get("tier"),
        "tier_capped": confidence.get("tier_capped"),
        "override_penalty_bp": confidence.get("override_penalty_bp"),
    }

    financial_state_payload = _build_financial_state_payload(
        schema_version=schema_version,
        config_version=config_version,
        deal_id=deal_id,
        currency=currency,
        transactions=sorted_txns,
        transfer_links=sorted_transfer_links,
        entities=sorted_entities,
        txn_entity_map=sorted_txn_entity_map,
        metrics=metrics_block,
        confidence=confidence_block,
    )

    financial_state_hash = compute_financial_state_hash(financial_state_payload)

    payload = {
        **financial_state_payload,
        "financial_state_hash": financial_state_hash,
        "reconciliation": reconciliation,
        "reconciliation_summary": reconciliation_summary,
        "overrides_applied": sorted(overrides_applied, key=lambda o: o.get("entity_id") or ""),
    }
    if audited_financials is not None:
        payload["audited_financials"] = audited_financials
    # Presentation-layer reconciliation (loan_activity / account_coverage / cash_position
    # / tier) sealed into canonical_json so the PDF renders from the hashed snapshot
    # instead of a live recompute. Added AFTER financial_state_hash so the outcome-only
    # financial_state_hash is unaffected (only sha256_hash changes for new snapshots).
    if recon_section is not None:
        payload["recon_section"] = recon_section
    return payload


def canonicalize_payload(payload: Dict[str, Any]) -> Tuple[str, str]:
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    sha = canonical_hash([payload])  # reuse canonical_hash utility
    return canonical_json, sha


def export_snapshot(
    *,
    snapshot_repo,
    deal_id: str,
    analysis_run_id: str,
    payload: Dict[str, Any],
    created_by: str,
) -> Dict[str, Any]:
    canonical_json, sha = canonicalize_payload(payload)
    existing = snapshot_repo.get_by_hash(sha)
    if existing:
        return existing
    stored_cj = compress_canonical_json_if_large(canonical_json)
    snapshot = {
        "id": str(uuid.uuid4()),
        "deal_id": deal_id,
        "analysis_run_id": analysis_run_id,
        "schema_version": payload["schema_version"],
        "config_version": payload["config_version"],
        "financial_state_hash": payload.get("financial_state_hash"),
        "sha256_hash": sha,
        "canonical_json": stored_cj,
        "created_by": created_by,
    }
    return snapshot_repo.insert_snapshot(snapshot)
