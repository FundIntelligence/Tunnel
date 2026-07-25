"""
Parity v1 — Golden hash sentinel.

Fixed fixture → deterministic sha256_hash. If this hash changes, CI fails.
Strongest determinism lock possible.
"""

import hashlib
import os
import sys
import unittest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.v1.config import SCHEMA_VERSION, CONFIG_VERSION
from backend.v1.core.pipeline import run_pipeline
from backend.v1.core.snapshot_engine import build_pds_payload, canonicalize_payload


def _txn(date, cents, desc, account="A", txn_id=None):
    tid = txn_id or hashlib.sha256(f"{date}|{account}|{cents}|{desc}".encode()).hexdigest()
    return {
        "txn_date": date,
        "signed_amount_cents": cents,
        "abs_amount_cents": abs(cents),
        "raw_descriptor": desc,
        "parsed_descriptor": desc.strip(),
        "normalized_descriptor": desc.strip().lower(),
        "account_id": account,
        "txn_id": tid,
        "is_transfer": False,
    }


# Fixed fixture — never modify. Hash must remain stable.
GOLDEN_FIXTURE = [
    _txn("2024-01-01", 25000, "Alpha Payment", "ACC-1", "s1"),
    _txn("2024-01-10", -8000, "Utility Bill", "ACC-1", "s2"),
    _txn("2024-02-01", 50000, "Client X", "ACC-2", "s3"),
    _txn("2024-02-15", -12000, "Office Rent", "ACC-2", "s4"),
    _txn("2024-03-01", 30000, "Client Y", "ACC-1", "s5"),
]

# Expected sha256_hash for GOLDEN_FIXTURE with current SCHEMA_VERSION/CONFIG_VERSION.
# If pipeline, snapshot_engine, or config changes, this must be updated explicitly.
#
# Updated 8 April 2026 — hash changed because snapshot payload now includes
# reconciliation and reconciliation_summary blocks from the core truth engine
# (snapshot_engine/build_pds_payload), which deterministically changes canonical JSON.
# Previous hash: e61407db11e40e7af2d76d593c7084125e4c98b74a7dbb8277bdad52cad5ccbb
#
# Updated 23 June 2026 — c227a0… → f2e98e68… . The sentinel had gone stale: two
# intentional changes already merged to BOTH main and paritystaging (the canonical
# hash-path files are byte-identical on both branches) drifted the canonical output
# without this expected value being refreshed. Bisected and verified — the delta is
# explained ENTIRELY by these two, nothing else in the canonical pipeline changed,
# and SCHEMA_VERSION is unchanged (still 1.0.2 — no sealed financial_state regression):
#   1. 3b76107 (20 May 2026) wired anomaly detection (annotate_anomalies) into
#      run_pipeline. It mutates each transaction dict in-place, and because the same
#      raw_transactions list is passed to both run_pipeline and build_pds_payload
#      (golden test here, AND production api.py:865/906), the "anomalies" key now
#      appears in the sealed canonical payload:  c227a0… → c029d75b… .
#   2. 61bd51e (13 May 2026) bumped CONFIG_VERSION 1.0.2 → 1.0.3 (payload field
#      "config_version"):  c029d75b… → f2e98e68… .
# Previous hash: c227a0add5e5268e9993be4a4449e0989ad0396179ea0b9299acd91f8f8d6b79
#
# ⚠ FLAG for maintainer review (not changed here — out of scope for the test fix):
# cause #1 means anomaly annotations are now sealed into every snapshot's canonical
# JSON via an in-place mutation of the caller's transaction list, rather than via a
# deliberate "include anomalies in the seal" decision in build_pds_payload. It is
# deterministic (the hash is stable and reproducible), so it is not a determinism
# bug — but whether anomaly data BELONGS in the immutable seal is a design question
# worth an explicit call. Touching it would require a SCHEMA_VERSION bump and is not
# part of this test-fix change.
#
# Updated 24 July 2026 — f2e98e68… → 96c74f19… . PAR-89: classifier.py's flat
# KES 100,000 large-positive-credit fallback replaced with a per-deal relative
# threshold (median + scaled MAD) plus an absolute ceiling; SCHEMA_VERSION
# bumped 1.0.2 → 1.0.3 and CONFIG_VERSION 1.0.3 → 1.0.4 in the same change
# (both intentional — see backend/v1/config.py). Two independent, deliberate
# causes, both expected to change this hash:
#   1. run_pipeline now stamps a "role_reason" string onto every
#      pds_txn_entity_map record (the human-readable flag reason, e.g. "KES
#      340,000 credit, no keyword match, 4.2x this business's median
#      transaction size"), which is part of the sealed txn_entity_map in the
#      canonical payload — same category as cause #1 above (a new field
#      entering the seal via a genuine, deliberate payload change).
#   2. CONFIG_VERSION bump (payload field "config_version") — same category
#      as cause #2 above, and required so already-exported deals actually
#      get reclassified under the new logic on next export() instead of
#      short-circuiting to a stale cached snapshot.
# None of the 5 golden fixture transactions are large enough to hit the
# large-positive fallback either before or after this change (max is KES 500),
# so no role changed here — only the new role_reason field and config_version.
# Previous hash: f2e98e6843e165af0316249add926fd5003e83fa696f60921eac72fb358be9d4
GOLDEN_HASH_EXPECTED = "96c74f190f58bd86a869e2d0ac18e2f9a991bd63d27d6bdfc4cc3ab2028332ae"


class TestGoldenHashSentinel(unittest.TestCase):
    """Golden hash sentinel — deterministic lock."""

    def test_golden_hash_unchanged(self):
        """Fixed fixture must produce exact expected sha256_hash."""
        run, links, ents, txm = run_pipeline(
            deal_id="d-golden",
            raw_transactions=GOLDEN_FIXTURE,
            overrides=[],
            accrual={},
        )
        payload = build_pds_payload(
            schema_version=SCHEMA_VERSION,
            config_version=CONFIG_VERSION,
            deal_id="d-golden",
            currency="USD",
            raw_transactions=GOLDEN_FIXTURE,
            transfer_links=links,
            entities=ents,
            txn_entity_map=txm,
            metrics={
                "coverage_bp": run["coverage_pct_bp"],
                "missing_month_count": run["missing_month_count"],
                "missing_month_penalty_bp": run["missing_month_penalty_bp"],
                "reconciliation_status": run["reconciliation_status"],
                "reconciliation_bp": run["reconciliation_pct_bp"],
            },
            confidence={
                "final_confidence_bp": run["final_confidence_bp"],
                "tier": run["tier"],
                "tier_capped": run["tier_capped"],
                "override_penalty_bp": run["override_penalty_bp"],
            },
            overrides_applied=[],
        )
        _, sha = canonicalize_payload(payload)
        self.assertEqual(
            sha,
            GOLDEN_HASH_EXPECTED,
            f"Golden hash changed. Pipeline/snapshot/config drift detected. "
            f"Got {sha} expected {GOLDEN_HASH_EXPECTED}. "
            f"Bump SCHEMA_VERSION and update GOLDEN_HASH_EXPECTED if intentional.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
