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

# PAR-89 part A: classifier.py's per-deal relative large-positive-credit
# threshold constants, moved here from classifier.py so they can be tuned
# without a code change once real review-queue usage data exists (see
# PAR-89 "revisit when" criteria). Values are UNCHANGED from what shipped
# in the original PAR-89 fix — this is a relocation + validation pass, not
# a retuning. No SCHEMA_VERSION/CONFIG_VERSION bump: classifier decision
# output is identical to before this move.

# Below this many transactions, a per-deal median/MAD is noise, not signal;
# classifier.py falls back to the flat threshold instead.
CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD = 30

# Modified z-score cutoff (Iglewicz & Hoaglin, 1993): threshold = median +
# (mad * NUM) // DEN, i.e. median + ~5.19 * MAD. Expressed as an exact
# integer ratio (7000/1349 ≈ 3.5/0.6745) rather than a float literal because
# classifier.py's money path may not contain float constants
# (test_no_float_regression.py). 3.5 is the standard modified-z-score
# cutoff; 0.6745 scales MAD to be comparable to a stddev under normality.
CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_NUM = 7000
CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_DEN = 1349

# Absolute ceiling: independent of any business's own transaction pattern, a
# single credit at or above this size always needs_review. Bounds the
# relative threshold; never applies to keyword-matched paths.
CLASSIFIER_ABSOLUTE_CEILING_CENTS = 500_000_000  # KES 5,000,000


def _validate_classifier_threshold_config() -> None:
    if CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD <= 0:
        raise ValueError(
            "CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD must be positive, "
            f"got {CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD}"
        )
    if CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD > 100_000:
        raise ValueError(
            "CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD implausibly large "
            f"(got {CLASSIFIER_MIN_SAMPLE_SIZE_FOR_RELATIVE_THRESHOLD}) — no real deal "
            "has this many transactions; every deal would silently use the flat fallback"
        )
    if CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_NUM <= 0 or CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_DEN <= 0:
        raise ValueError(
            "CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_NUM/DEN must both be positive, got "
            f"{CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_NUM}/{CLASSIFIER_MODIFIED_Z_SCORE_MULTIPLIER_DEN}"
        )
    if CLASSIFIER_ABSOLUTE_CEILING_CENTS <= 0:
        raise ValueError(
            f"CLASSIFIER_ABSOLUTE_CEILING_CENTS must be positive, got {CLASSIFIER_ABSOLUTE_CEILING_CENTS}"
        )
    if CLASSIFIER_ABSOLUTE_CEILING_CENTS < 100_000_00:  # KES 100,000
        raise ValueError(
            "CLASSIFIER_ABSOLUTE_CEILING_CENTS below the original flat KES 100,000 threshold "
            f"(got {CLASSIFIER_ABSOLUTE_CEILING_CENTS} cents) — this would make the ceiling stricter "
            "than the pre-PAR-89 baseline, which is almost certainly not intended"
        )


_validate_classifier_threshold_config()
