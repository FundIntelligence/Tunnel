"""
Regression test: abs_amount_cents must never be sent to the database (PAR-160).

PR #61 found staging's abs_amount_cents rendering as NULL and concluded the
column was a plain writable bigint everywhere, so it stopped stripping the
key before insert. That held on staging but not on prod: prod's column is
GENERATED ALWAYS AS (abs(signed_amount_cents)) STORED
(supabase/migrations/002_pds_v1.sql, 003_pds_v1_prefixed.sql), and Postgres
rejects any explicit value for a generated column. Sending it caused
postgrest APIError 428C9 on every insert during the 2026-08-17 promotion,
taking down all document ingestion prod-wide for ~20 minutes.

Stripping it here does not reintroduce PR #61's display bug:
snapshot_html_renderer.py derives abs_amount_cents from signed_amount_cents
whenever the stored value is NULL, independent of what ingestion sends.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from v1.ingestion.service import IngestionService


def _make_service():
    documents_repo = MagicMock()
    raw_tx_repo = MagicMock()
    raw_tx_repo.insert_batch = MagicMock()
    analysis_repo = MagicMock()
    return IngestionService(
        documents_repo=documents_repo,
        raw_tx_repo=raw_tx_repo,
        analysis_repo=analysis_repo,
    ), raw_tx_repo


def test_ingest_strips_abs_amount_cents():
    service, raw_tx_repo = _make_service()
    fake_row = {
        "txn_date": "2026-03-02",
        "signed_amount_cents": -50000,
        "abs_amount_cents": 50000,
        "normalized_descriptor": "test row",
        "balance_cents": 100000,
    }
    with patch(
        "v1.ingestion.service.parse_file",
        return_value=([dict(fake_row)], "fakehash", "KES", {}),
    ):
        service.ingest(
            deal_id="deal-1",
            created_by="user-1",
            file_bytes=b"irrelevant",
            file_name="test.csv",
            file_type="csv",
            deal_currency="KES",
        )

    raw_tx_repo.insert_batch.assert_called_once()
    inserted_rows = raw_tx_repo.insert_batch.call_args[0][0]
    assert len(inserted_rows) == 1
    assert "abs_amount_cents" not in inserted_rows[0]
    assert inserted_rows[0]["signed_amount_cents"] == -50000
