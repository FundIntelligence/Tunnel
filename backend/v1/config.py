"""
Parity v1 — Canonical version constants.

These are the single source of truth for version strings used in
analysis_runs, snapshot payloads, and the system identity endpoint.
"""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

# PAR-89 (this bump): classifier.py's large-positive fallback replaced with a
# per-deal relative threshold (median + scaled MAD) + absolute ceiling, and
# pds_txn_entity_map rows now carry a role_reason string. Both the classifier
# vocabulary/role-output guard and the export() snapshot cache short-circuit
# key off these versions — bumping both here is required so (a) CI's
# classifier guard passes and (b) already-exported deals actually get
# reclassified under the new logic on next export() rather than silently
# reusing a stale cached snapshot computed under the old flat threshold.
SCHEMA_VERSION = "1.0.3"
_CONFIG_VERSION_BASE = "1.0.4"

# ---------------------------------------------------------------------------
# PAR-219: computation fingerprint
# ---------------------------------------------------------------------------
# The export() snapshot cache short-circuit keys off CONFIG_VERSION. Before
# this, that meant a computation-logic fix only reached already-sealed deals
# if a human also remembered to hand-bump _CONFIG_VERSION_BASE above. PAR-217
# shipped a real reconciliation fix without that bump, so every sealed deal
# kept serving pre-fix figures while every other signal (PR merged, build
# SUCCESS, revision at 100% traffic, export HTTP 200) looked healthy. See
# PAR-219.
#
# Fix: derive a short digest of the *actual source* of every module that can
# change a computed figure, and append it to CONFIG_VERSION. Any real edit to
# computation logic changes the digest, which changes CONFIG_VERSION, which
# invalidates the cache automatically — no human step to forget.
#
# Deliberately NOT keyed on GIT_COMMIT or BUILD_TIMESTAMP, both of which were
# considered and rejected against the real deployed environment:
#   * GIT_COMMIT is unset on the deployed service (confirmed via
#     /v1/system/health returning "git_commit": null), so it would be None on
#     every revision and never invalidate anything.
#   * BUILD_TIMESTAMP falls back to *process start time* when unset (it is
#     unset), so it changes on every cold start and autoscale event — that
#     would re-seal every snapshot in the system repeatedly for no reason.
#
# Scope is deliberately narrow: only modules whose code can alter a number in
# the snapshot. Presentation-layer modules (snapshot_html_renderer.py,
# pdf_generator.py) are intentionally EXCLUDED so a template/copy change of
# the kind PAR-206/207/208 shipped does not needlessly re-compute and re-seal
# every deal in the system. Renderer changes affect how a figure is drawn,
# not what it is.
_COMPUTATION_MODULES = (
    "core/pipeline.py",
    "core/classifier.py",
    "core/metrics_engine.py",
    "core/confidence_engine.py",
    "core/transfer_matcher.py",
    "core/entities.py",
    "core/anomaly_detector.py",
    "core/reconciliation.py",
    "core/declared_financials.py",
    "core/snapshot_engine.py",
    "analysis/reconciliation_engine.py",
    "analysis/snapshot_context.py",
    "analysis/snapshot_generator.py",
)


def _compute_logic_fingerprint() -> str:
    """Short, stable digest of every computation module's source bytes.

    Sorted, length-prefixed, and salted with each module's relative path so
    the digest cannot collide by reordering or by two files swapping content.
    A missing file contributes a sentinel rather than raising: a fingerprint
    that silently degrades to "different" is safe (it over-invalidates once),
    whereas raising here would take the whole service down at import time.
    """
    base = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for rel in sorted(_COMPUTATION_MODULES):
        digest.update(rel.encode("utf-8"))
        try:
            payload = (base / rel).read_bytes()
        except OSError:
            payload = b"<unreadable>"
        digest.update(str(len(payload)).encode("utf-8"))
        digest.update(payload)
    return digest.hexdigest()[:12]


COMPUTATION_FINGERPRINT = _compute_logic_fingerprint()

# IMPORTANT: the fingerprint is deliberately NOT folded into CONFIG_VERSION.
#
# config_version is part of the canonical snapshot payload and therefore feeds
# sha256_hash / financial_state_hash (see core/snapshot_engine.py's
# build_financial_state / canonicalize_payload). Appending a source digest to
# it would make every deal's sealed hash change on any computation edit, break
# the golden-hash sentinel, and re-seal documents whose figures never moved —
# a far broader blast radius than the caching bug PAR-219 is about, and a
# change to a deterministic-rules invariant rather than a cache fix.
#
# Instead the fingerprint is consumed *only* by export()'s short-circuit, via
# the pds_analysis_runs.run_trigger side-channel, so it can invalidate a stale
# cache without ever entering a hash. CONFIG_VERSION keeps its exact prior
# meaning and value.
CONFIG_VERSION = _CONFIG_VERSION_BASE

# Upload limits
MAX_PDF_FILES = 20          # max files per single batch upload operation
MAX_BATCH_UPLOADS = 20      # max distinct batch upload operations per deal

GIT_COMMIT = os.getenv("GIT_COMMIT") or None
BUILD_TIMESTAMP = os.getenv("BUILD_TIMESTAMP") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
DETERMINISTIC_MODE = True
