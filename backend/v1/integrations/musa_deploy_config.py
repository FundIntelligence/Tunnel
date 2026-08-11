"""
Musa integration — deploy-time config, read once from env vars.

PAR-59: Uzoma's Jul 3 pushback was that every Musa config change forced a
redeploy to a new domain, and he had to update his webhook URL by hand.
Root cause was a mix of (a) historical free-tier Render churn (gone now —
we're on Cloud Run with a fixed service name/domain per environment) and
(b) these two values being read via `os.getenv(..., <hardcoded domain>)`
at five separate call sites, each with its own copy-pasted fallback.

The fallbacks were themselves the bug: if the env var was ever unset on a
real deploy, code silently fell back to `https://parity-ingestion.onrender.com`
(a decommissioned Render service) or `https://parity-sme-staging.vercel.app`
(hardcoded staging, even from a production deploy). Both are wrong in a
"one binary, config differs per environment" world — there is no single
default that's correct for every environment, so there is no safe default.

No fallback here on purpose. If unset, we log loudly at import time so a
misconfigured deploy is caught immediately instead of silently mailing
Musa (or the internal team) a dead or wrong-environment URL.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Base URL of THIS backend deployment (e.g. the staging or prod Cloud Run
# service URL). Used to build the status_url/pdf_url links handed to Musa
# in webhook payloads sent from background tasks, which have no incoming
# Request to derive it from (request.base_url is used instead wherever a
# live request is available — see musa_api.py's POST/GET handlers).
API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")

# Base URL of the Next.js frontend for THIS environment, used only for the
# internal "unparseable file" team-notify POST to /api/request-parser.
PARITY_FRONTEND_URL = os.getenv("PARITY_FRONTEND_URL", "").rstrip("/")

if not API_BASE_URL:
    logger.error(
        "[MUSA] API_BASE_URL is not set — webhook status_url/pdf_url links "
        "sent to Musa from background tasks will be malformed. Set it to "
        "this environment's own Cloud Run service URL."
    )

if not PARITY_FRONTEND_URL:
    logger.error(
        "[MUSA] PARITY_FRONTEND_URL is not set — the internal unparseable-file "
        "notify POST will be malformed. Set it to this environment's own "
        "frontend URL."
    )
