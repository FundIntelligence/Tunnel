import sys
from pathlib import Path
from unittest.mock import MagicMock

import bcrypt
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as app_main  # noqa: E402
from app import usage as app_usage  # noqa: E402
from v1.integrations import auth  # noqa: E402


def hash_key(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


@pytest.fixture
def client():
    return TestClient(app_main.app)


@pytest.fixture
def mock_supabase(monkeypatch):
    """Patches get_supabase everywhere it's imported (auth.py's module-level
    binding used by require_scoped_api_key, and usage.py's, used for the
    row lookup + increment_api_key_usage RPC). Callers configure
    mock_sb.table(...)...execute().data and mock_sb.rpc(...).execute().data
    per test."""
    mock_sb = MagicMock()
    monkeypatch.setattr(auth, "get_supabase", lambda: mock_sb)
    monkeypatch.setattr(app_usage, "get_supabase", lambda: mock_sb)
    return mock_sb


def configure_key_row(mock_sb, *, raw_key: str, status: str = "active", calls_used: int = 0, call_cap: int = 10):
    """Wires mock_sb so a table().select()...execute() lookup returns one
    api_keys row matching raw_key, and rpc("increment_api_key_usage", ...)
    behaves like the real UPDATE...RETURNING guard: NULL/empty when
    status != 'active' or calls_used >= call_cap, else the updated row."""
    row = {"id": "11111111-1111-1111-1111-111111111111", "api_key_hash": hash_key(raw_key)}
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [row]

    guard_passes = status == "active" and calls_used < call_cap
    updated_row = {**row, "calls_used": calls_used + 1, "call_cap": call_cap, "status": status} if guard_passes else None
    mock_sb.rpc.return_value.execute.return_value.data = [updated_row] if updated_row else []
    return row
