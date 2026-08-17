"""
Regression test: abs_amount_cents must reach the database.

Found while investigating why "Outflow composition" and "Loan activity"
totals rendered as KES 0 across every deal on staging (153,367/153,367
raw transactions had abs_amount_cents = NULL). The column is a plain
nullable bigint, not a DB-generated column as the removed comment
claimed — IngestionService was popping the parser's already-correct
value off every row before insert, so nothing ever populated it.
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


def test_ingest_does_not_strip_abs_amount_cents():
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
    assert inserted_rows[0]["abs_amount_cents"] == 50000
    assert inserted_rows[0]["signed_amount_cents"] == -50000
