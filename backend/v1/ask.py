"""
Parity Review — Minimal Q&A module.

LLM = intent classifier only. All arithmetic is deterministic and done here.
Never import pipeline, classifier, or hashing utilities. Snapshot helpers that only
decode stored JSON blobs are allowed.
"""

import json
import logging
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .core.snapshot_engine import decompress_canonical_json_if_needed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent taxonomy
# ---------------------------------------------------------------------------

ALLOWED_INTENTS = frozenset({
    "total_revenue",
    "total_payroll",
    "top_suppliers",
    "top_revenue_entities",
    "revenue_by_month",
    "payroll_percent_revenue",
    "confidence_explain",
    "reconciliation_explain",
})

# Keyword patterns for zero-dependency fallback (checked before LLM call)
_KEYWORD_MAP = [
    ("payroll_percent_revenue", ["payroll.*percent", "percent.*payroll", "payroll.*revenue",
                                  "payroll.*proportion", "payroll.*ratio", "payroll.*share",
                                  "what.*payroll.*of", "how much.*payroll"]),
    ("total_revenue",           ["total.*revenue", "revenue.*total", "operational revenue",
                                  "how much.*revenue", "revenue.*amount"]),
    ("total_payroll",           ["total.*payroll", "payroll.*total", "payroll.*spend",
                                  "payroll.*cost", "how much.*payroll", "salary.*total"]),
    ("top_suppliers",           ["top.*supplier", "supplier.*top", "biggest.*supplier",
                                  "largest.*supplier", "supplier.*spend", "who.*supplier"]),
    ("top_revenue_entities",    ["top.*revenue.*entit", "revenue.*source", "biggest.*client",
                                  "top.*client", "top.*customer", "who.*revenue"]),
    ("revenue_by_month",        ["revenue.*month", "month.*revenue", "monthly.*revenue",
                                  "revenue.*breakdown", "revenue.*over.*time"]),
    ("confidence_explain",      ["confidence", "how.*confident", "analysis.*score",
                                  "quality.*score", "data.*quality", "why.*score"]),
    ("reconciliation_explain",  ["reconcil", "accrual", "bank.*data.*match", "match.*revenue",
                                  "declared.*revenue", "does.*bank"]),
]

_SYSTEM_PROMPT = (
    "You are an intent classifier for Parity Review. "
    "Return only valid JSON with the single key \"intent\". "
    "Do not compute numbers. Do not explain. Do not add any other keys."
)

_USER_TEMPLATE = (
    "Classify the following analyst question into exactly one intent.\n"
    "Allowed intents: {intents}\n\n"
    "Question: {question}"
)

# ---------------------------------------------------------------------------
# Intent classifier (LLM — reads intent only, never touches numbers)
# ---------------------------------------------------------------------------


def _keyword_classify(question: str) -> Optional[str]:
    """Fast keyword-based classification — no network call required."""
    import re
    q = question.lower()
    for intent, patterns in _KEYWORD_MAP:
        if any(re.search(p, q) for p in patterns):
            logger.info("[ask] keyword match intent=%s q=%r", intent, question[:60])
            return intent
    return None


def classify_intent(question: str) -> Optional[str]:
    """
    Classify intent via keyword matching first, then OpenAI fallback.
    Returns the intent string if valid, None if out-of-scope or API error.
    """
    # Primary: keyword matching (fast, zero-dependency)
    intent = _keyword_classify(question)
    if intent:
        return intent

    # Fallback: LLM (only if keyword matching finds no match)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        logger.warning("[ask] OPENAI_API_KEY not set — returning None")
        return None

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_TEMPLATE.format(
                        intents=", ".join(sorted(ALLOWED_INTENTS)),
                        question=question,
                    ),
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=50,
            temperature=0,
        )
        raw = response.choices[0].message.content
    except Exception as exc:
        logger.warning("[ask] OpenAI call failed: %s", exc)
        return None

    try:
        parsed = json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        logger.warning("[ask] Invalid JSON from LLM: %r", raw)
        return None

    intent = parsed.get("intent")
    if intent not in ALLOWED_INTENTS:
        logger.info("[ask] Intent %r not in ALLOWED_INTENTS", intent)
        return None

    return intent


def classify_intent_debug(question: str):
    """Wrapper returning (intent, debug_info) for temporary diagnostics."""
    kw = _keyword_classify(question)
    if kw:
        return kw, {"method": "keyword", "intent": kw}
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, {"error": "OPENAI_API_KEY not set"}
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_TEMPLATE.format(
                    intents=", ".join(sorted(ALLOWED_INTENTS)), question=question)},
            ],
            response_format={"type": "json_object"},
            max_tokens=50,
            temperature=0,
        )
        raw = response.choices[0].message.content
    except Exception as exc:
        return None, {"error": f"openai_error: {exc}"}
    try:
        parsed = json.loads(raw or "")
    except Exception:
        return None, {"error": "invalid_json", "raw": raw}
    intent = parsed.get("intent")
    dbg = {"raw": raw, "intent": intent, "allowed": sorted(ALLOWED_INTENTS)}
    if intent not in ALLOWED_INTENTS:
        return None, dbg
    return intent, dbg


# ---------------------------------------------------------------------------
# Aggregate extractor — reads snapshot canonical_json, produces plain dicts
# ---------------------------------------------------------------------------


def extract_aggregates(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse the snapshot's canonical_json and join txn_entity_map onto transactions
    so each transaction carries its role and entity_id.
    """
    data = json.loads(decompress_canonical_json_if_needed(snapshot["canonical_json"]))
    transactions: List[Dict] = data.get("transactions", [])
    txn_entity_map: List[Dict] = data.get("txn_entity_map", [])
    entities: List[Dict] = data.get("entities", [])
    metrics: Dict = data.get("metrics", {})
    confidence: Dict = data.get("confidence", {})
    currency: str = data.get("currency", "")

    # Build lookup maps
    role_map = {m["txn_id"]: m["role"] for m in txn_entity_map}
    entity_id_map = {m["txn_id"]: m["entity_id"] for m in txn_entity_map}
    entity_names = {
        e["entity_id"]: e.get("display_name") or e.get("entity_id", "")
        for e in entities
    }

    # Tag each transaction with its role and entity_id
    tagged: List[Dict] = []
    for tx in transactions:
        tid = tx.get("id") or tx.get("txn_id", "")
        tagged.append({
            **tx,
            "role": role_map.get(tid, "other"),
            "entity_id": entity_id_map.get(tid, ""),
        })

    return {
        "tagged": tagged,
        "entity_names": entity_names,
        "metrics": metrics,
        "confidence": confidence,
        "currency": currency,
    }


# ---------------------------------------------------------------------------
# Deterministic answer computation — no LLM, integer arithmetic throughout
# ---------------------------------------------------------------------------


def answer_intent(intent: str, agg: Dict[str, Any]) -> str:
    tagged: List[Dict] = agg["tagged"]
    entity_names: Dict[str, str] = agg["entity_names"]
    metrics: Dict = agg["metrics"]
    confidence: Dict = agg["confidence"]
    currency: str = agg["currency"]

    if intent == "total_revenue":
        revenue_cents = sum(
            int(t["signed_amount_cents"])
            for t in tagged
            if t["role"] == "revenue_operational" and int(t["signed_amount_cents"]) > 0
        )
        return f"Total operational revenue: {currency} {revenue_cents / 100:,.2f}"

    if intent == "total_payroll":
        payroll_cents = sum(
            abs(int(t["signed_amount_cents"]))
            for t in tagged
            if t["role"] == "payroll"
        )
        return f"Total payroll: {currency} {payroll_cents / 100:,.2f}"

    if intent == "payroll_percent_revenue":
        revenue_cents = sum(
            int(t["signed_amount_cents"])
            for t in tagged
            if t["role"] == "revenue_operational" and int(t["signed_amount_cents"]) > 0
        )
        payroll_cents = sum(
            abs(int(t["signed_amount_cents"]))
            for t in tagged
            if t["role"] == "payroll"
        )
        if revenue_cents <= 0:
            return "No operational revenue found to compute payroll percentage."
        pct_bp = payroll_cents * 10000 // revenue_cents
        pct = pct_bp / 100
        return f"Payroll represents {pct:.1f}% of operational revenue."

    if intent == "top_suppliers":
        entity_totals: Dict[str, int] = defaultdict(int)
        for t in tagged:
            if t["role"] == "supplier":
                entity_totals[t["entity_id"]] += abs(int(t["signed_amount_cents"]))
        top = sorted(entity_totals.items(), key=lambda x: x[1], reverse=True)[:5]
        if not top:
            return "No supplier transactions found."
        lines = [
            f"  {entity_names.get(eid, eid)}: {currency} {cents / 100:,.2f}"
            for eid, cents in top
        ]
        return "Top suppliers by spend:\n" + "\n".join(lines)

    if intent == "top_revenue_entities":
        entity_totals: Dict[str, int] = defaultdict(int)
        for t in tagged:
            if t["role"] == "revenue_operational" and int(t["signed_amount_cents"]) > 0:
                entity_totals[t["entity_id"]] += int(t["signed_amount_cents"])
        top = sorted(entity_totals.items(), key=lambda x: x[1], reverse=True)[:5]
        if not top:
            return "No operational revenue entities found."
        lines = [
            f"  {entity_names.get(eid, eid)}: {currency} {cents / 100:,.2f}"
            for eid, cents in top
        ]
        return "Top revenue entities:\n" + "\n".join(lines)

    if intent == "revenue_by_month":
        monthly: Dict[str, int] = defaultdict(int)
        for t in tagged:
            if t["role"] == "revenue_operational" and int(t["signed_amount_cents"]) > 0:
                month = str(t.get("txn_date", ""))[:7]
                if month:
                    monthly[month] += int(t["signed_amount_cents"])
        if not monthly:
            return "No operational revenue transactions found."
        lines = [
            f"  {month}: {currency} {cents / 100:,.2f}"
            for month, cents in sorted(monthly.items())
        ]
        return "Revenue by month:\n" + "\n".join(lines)

    if intent == "confidence_explain":
        final_bp = int(confidence.get("final_confidence_bp", 0))
        tier = confidence.get("tier", "Unknown")
        capped = confidence.get("tier_capped", False)
        missing = int(metrics.get("missing_month_count", 0))
        recon = metrics.get("reconciliation_status", "NOT_RUN")
        pct = final_bp / 100
        parts = [f"Confidence score: {pct:.1f}% ({tier} tier)."]
        if missing > 0:
            penalty_bp = int(metrics.get("missing_month_penalty_bp", missing * 1000))
            parts.append(
                f"{missing} missing month(s) detected, applying a {penalty_bp / 100:.0f}% penalty."
            )
        if recon == "NOT_RUN":
            parts.append("Accrual reconciliation was not run (no accrual data provided).")
        elif recon == "FAILED_OVERLAP":
            parts.append("Accrual reconciliation failed due to insufficient period overlap.")
        elif recon == "OK":
            recon_bp = int(metrics.get("reconciliation_bp") or 0)
            parts.append(f"Accrual reconciliation passed with a score of {recon_bp / 100:.1f}%.")
        if capped:
            parts.append("Tier capped at Medium because reconciliation did not complete.")
        return " ".join(parts)

    if intent == "reconciliation_explain":
        recon = metrics.get("reconciliation_status", "NOT_RUN")
        if recon == "NOT_RUN":
            return (
                "Accrual reconciliation was not run. "
                "No accrual revenue figures were provided when the deal was created."
            )
        if recon == "FAILED_OVERLAP":
            return (
                "Reconciliation failed. The accrual period and the bank transaction period "
                "have less than 60% calendar overlap, making comparison unreliable."
            )
        if recon == "OK":
            recon_bp = int(metrics.get("reconciliation_bp") or 0)
            pct = recon_bp / 100
            return (
                f"Reconciliation passed with a score of {pct:.1f}%. "
                "Bank operational inflows align with the provided accrual revenue figures."
            )
        return f"Reconciliation status: {recon}."

    # Should not be reachable if ALLOWED_INTENTS is consistent with this function
    return "This question is outside supported scope."
