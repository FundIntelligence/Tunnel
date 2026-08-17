"""
Controlled progressive test fixtures for ingestion error taxonomy.
No random files — explicit fixtures with known outcomes.
"""

import io
import os
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.v1.api import router as v1_router
from backend.v1.db.memory_repositories import build_memory_repos


def _make_app():
    repos = build_memory_repos()
    app = FastAPI()
    app.state.repos_factory = lambda: repos
    app.include_router(v1_router)
    return app, repos


def _read_fixture(name: str) -> bytes:
    path = Path(_FIXTURES) / name
    return path.read_bytes()


class TestIngestionErrors(unittest.TestCase):
    """Structured error taxonomy and fixture-based ingestion tests."""

    @classmethod
    def setUpClass(cls):
        cls.app, cls.repos = _make_app()
        cls.client = TestClient(cls.app)

    def _new_deal(self, currency="USD"):
        resp = self.client.post("/v1/deals", data={"currency": currency})
        self.assertEqual(resp.status_code, 200)
        return resp.json()["deal"]

    def test_a_minimal_valid_bank_succeeds(self):
        """Fixture A: minimal_valid_bank.csv must end status=completed."""
        deal = self._new_deal()
        content = _read_fixture("minimal_valid_bank.csv")
        resp = self.client.post(
            f"/v1/deals/{deal['id']}/documents",
            files={"file": ("minimal_valid_bank.csv", content, "text/csv")},
        )
        self.assertEqual(resp.status_code, 200)
        doc_id = resp.json()["ingestion"]["document_id"]
        status = self.client.get(f"/v1/documents/{doc_id}/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed", status.json())

    def test_b_minimal_valid_pds_fails_schema_validation(self):
        """Fixture B: canonical PDS format has different schema → InvalidSchemaError."""
        deal = self._new_deal()
        content = _read_fixture("minimal_valid_pds.csv")
        resp = self.client.post(
            f"/v1/deals/{deal['id']}/documents",
            files={"file": ("minimal_valid_pds.csv", content, "text/csv")},
        )
        self.assertEqual(resp.status_code, 200)
        doc_id = resp.json()["ingestion"]["document_id"]
        status = self.client.get(f"/v1/documents/{doc_id}/status")
        self.assertEqual(status.status_code, 200)
        data = status.json()
        self.assertEqual(data["status"], "failed", data)
        # The ingestion path raises InvalidSchemaError (parsing/errors.py) and
        # reports it verbatim as error_type (ingestion/service.py:331).
        # SchemaValidationError (errors.py) is a separate class not used here.
        self.assertEqual(data.get("error_type"), "InvalidSchemaError", data)
        self.assertIn("Missing required", data.get("error_message", ""))
        self.assertIn(data.get("stage"), ("SCHEMA_VALIDATED", "PARSE_START", "PARSE_DONE"))
        self.assertEqual(data.get("next_action"), "fix_csv_header")

    def test_c_accrual_free_no_crash(self):
        """Fixture C: accrual-free upload must not crash (recon can be NOT_RUN)."""
        deal = self._new_deal()
        content = _read_fixture("minimal_accrual_free.csv")
        resp = self.client.post(
            f"/v1/deals/{deal['id']}/documents",
            files={"file": ("minimal_accrual_free.csv", content, "text/csv")},
        )
        self.assertEqual(resp.status_code, 200)
        doc_id = resp.json()["ingestion"]["document_id"]
        status = self.client.get(f"/v1/documents/{doc_id}/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed", status.json())

    def test_d_bad_schema_missing_amount_explicit_error(self):
        """Fixture D: missing amount column → InvalidSchemaError with explicit message."""
        deal = self._new_deal()
        content = _read_fixture("bad_schema_missing_amount.csv")
        resp = self.client.post(
            f"/v1/deals/{deal['id']}/documents",
            files={"file": ("bad_schema_missing_amount.csv", content, "text/csv")},
        )
        self.assertEqual(resp.status_code, 200)
        doc_id = resp.json()["ingestion"]["document_id"]
        status = self.client.get(f"/v1/documents/{doc_id}/status")
        self.assertEqual(status.status_code, 200)
        data = status.json()
        self.assertEqual(data["status"], "failed", data)
        self.assertEqual(data.get("error_type"), "InvalidSchemaError", data)
        self.assertIn("amount", data.get("error_message", "").lower())
        self.assertIn(data.get("stage"), ("SCHEMA_VALIDATED", "PARSE_DONE", "PARSE_START"))
        self.assertEqual(data.get("next_action"), "fix_csv_header")

    def test_failed_status_has_structured_fields(self):
        """Every failed status includes error_type, error_message, stage, next_action."""
        deal = self._new_deal()
        content = b"date,description,balance\n2024-01-01,Foo,100\n"  # missing amount
        resp = self.client.post(
            f"/v1/deals/{deal['id']}/documents",
            files={"file": ("bad.csv", content, "text/csv")},
        )
        self.assertEqual(resp.status_code, 200)
        doc_id = resp.json()["ingestion"]["document_id"]
        status = self.client.get(f"/v1/documents/{doc_id}/status")
        data = status.json()
        self.assertEqual(data["status"], "failed")
        for key in ("error_type", "error_message", "stage", "next_action"):
            self.assertIn(key, data, f"Missing {key} in failed status")
            self.assertTrue(data[key], f"{key} must be non-empty")
