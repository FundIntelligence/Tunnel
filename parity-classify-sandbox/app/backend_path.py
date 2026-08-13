"""
Makes the real backend/v1 package importable without copying or forking it.

This service is intentionally isolated from api.py (PAR-132), but the core
engine (classifier.py, metrics_engine.py) and the PAR-131 scoped-auth helpers
in v1/integrations/auth.py are meant to be reused, not duplicated — a fork
would drift from the source of truth the main backend already tests. The
Docker build context is the repo root so backend/ ships alongside this
service's own directory (see Dockerfile); locally the two are already
siblings inside the same worktree.
"""
import sys
from pathlib import Path

# Locally this file sits at <repo>/parity-classify-sandbox/app/backend_path.py,
# three levels below <repo>/backend. In the container (Dockerfile copies
# app/ and backend/ as direct siblings under /app) it's only two levels
# below /app/backend. Walk up instead of hardcoding a level count so both
# layouts resolve the same way.
def _find_backend_dir() -> Path:
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "backend" / "v1" / "core" / "classifier.py"
        if candidate.is_file():
            return ancestor / "backend"
    raise RuntimeError("Could not locate backend/v1/core/classifier.py from any ancestor directory")


_BACKEND_DIR = _find_backend_dir()

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
