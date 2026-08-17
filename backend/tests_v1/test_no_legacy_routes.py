"""
Regression test: no legacy API routes.
All routes must be under /v1 except excluded paths.
"""

import os
import sys
import unittest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# Import app from backend.main (run from project root)
from backend.main import app

class TestNoLegacyRoutes(unittest.TestCase):
    """Ensure no non-v1 routes exist."""

    def test_all_routes_under_v1_or_excluded(self):
        """Every route path must start with /v1 or be excluded (health, docs, etc.)."""
        for route in app.routes:
            if not hasattr(route, "path"):
                continue
            path = route.path
            if path == "/" or path == "/health":
                continue
            if path.startswith("/docs") or path == "/openapi.json" or path.startswith("/redoc"):
                continue
            # /api/musa is the Musa Ventures partner integration namespace — an
            # intentional external-facing webhook API (musa_api.py, prefix
            # "/api/musa", included in main.py), with its own api_keys auth. It is
            # deliberately not under /v1; moving it would break the partner's
            # webhook URLs. Excluded here like /health and /docs.
            if path.startswith("/api/musa"):
                continue
            self.assertTrue(
                path.startswith("/v1"),
                f"Legacy route detected: {path}. All routes must be under /v1.",
            )
