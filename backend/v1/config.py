"""
Parity v1 — Canonical version constants.

These are the single source of truth for version strings used in
analysis_runs, snapshot payloads, and the system identity endpoint.
"""

import os
from datetime import datetime, timezone

# PAR-89 (this bump): classifier.py's large-positive fallback replaced with a
# per-deal relative threshold (median + scaled MAD) + absolute ceiling, and
# pds_txn_entity_map rows now carry a role_reason string. Both the classifier
# vocabulary/role-output guard and the export() snapshot cache short-circuit
# key off these versions — bumping both here is required so (a) CI's
# classifier guard passes and (b) already-exported deals actually get
# reclassified under the new logic on next export() rather than silently
# reusing a stale cached snapshot computed under the old flat threshold.
SCHEMA_VERSION = "1.0.3"
CONFIG_VERSION = "1.0.4"

# Upload limits
MAX_PDF_FILES = 20          # max files per single batch upload operation
MAX_BATCH_UPLOADS = 20      # max distinct batch upload operations per deal

GIT_COMMIT = os.getenv("GIT_COMMIT") or None
BUILD_TIMESTAMP = os.getenv("BUILD_TIMESTAMP") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
DETERMINISTIC_MODE = True
