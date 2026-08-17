"""
Phase 2: the audited-financials ingestion hot path now extracts via the Claude
extractor (extract_audited_financials_claude), not the old pdfplumber/parity-
ingestion client.

These tests run end-to-end through the real FastAPI upload route
(POST /v1/deals/{deal_id}/upload-financials) in backend/v1/api.py, with only the
Claude extractor itself patched (it makes a network call to the Anthropic API,
which must not happen in CI). Everything downstream of extraction — the NOT-NULL
financial_year guard, sha256_hash derivation, currency-default handling,
confirmed_at=NULL stamping, and the upsert — runs the genuine endpoint code.

Two behaviours are pinned here that are specific to the swap:

  1. A representative successful extraction is persisted as unconfirmed
     (confirmed_at IS NULL), and the new fields the Claude extractor produces
     (auditor_name, loan_breakdown, the granular liability fields) round-trip.

  2. A "scanned PDF" extraction succeeds with NO extraction_confidence at all.
     The OLD path raised AuditedFinancialsExtractionError("...confidence is
     zero") on exactly this case (scanned PDFs scored 0 -> PARSE_FAILED 422,
     see AUDITED_FINANCIALS_EXTRACTION_INVESTIGATION.md section 6.3). The new
     path has no confidence==0 gate, so a confidence-less success must persist
     cleanly as a 200 with extraction_confidence NULL.

The live proof that Claude actually reads scanned PDFs (3 real scanned files —
Tawi Fresh, Maharaji, Tres Beau — all HTTP 200 through this exact endpoint) is
recorded in the PR description; it can't live in CI because those real client
files are gitignored and not committed.
"""
import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v1.api import router as v1_router
from backend.v1.db.memory_repositories import build_memory_repos


# A representative text-layer audit extraction (Kenlink-shaped: real values from
# AUDITED_FINANCIALS_EXTRACTION_INVESTIGATION.md section 10.2, in cents). Mirrors
# the exact shape extract_audited_financials_claude returns: null confidence,
# extraction_method set, _usage attached, total_liabilities_cents recomputed,
# loan_breakdown present.
def _fake_text_layer_extraction(file_bytes, file_name):
    return {
        "company_name": "Kenlinks Limited",
        "financial_year": 2025,
        "financial_year_start": "2025-01-01",
        "financial_year_end": "2025-12-31",
        "currency": "KES",
        "auditor_name": "Some Auditor LLP",
        "turnover_cents": 20_790_711_00,
        "cost_of_sales_cents": 16_995_067_20,
        "profit_after_tax_cents": 1_756_021_70,
        "total_assets_cents": 7_190_431_80,
        "cash_and_equivalents_cents": 60_109_500,
        "trade_payables_cents": 2_476_020,
        "tax_payable_cents": None,
        "short_term_loans_cents": 2_086_730,
        "long_term_loans_cents": 3_842_461,
        "other_payables_cents": 4_499,
        "total_liabilities_cents": 8_409_710,
        "loan_breakdown": [
            {"name": "Short Term Loan", "reference": None, "type": "Term Loan",
             "amount_cents": 2_086_730},
        ],
        "cash_breakdown": {"Bank": 60_109_500},
        # No extraction_confidence key — Claude doesn't produce one.
        "extraction_method": "claude_sonnet_4_6",
        "_usage": {"input_tokens": 25_174, "output_tokens": 806},
    }


# A "scanned PDF" extraction: same successful shape, deliberately WITHOUT any
# extraction_confidence key — the case the old OCR path scored 0 on and rejected.
def _fake_scanned_extraction(file_bytes, file_name):
    return {
        "company_name": "Tawi Fresh Kenya Limited",
        "financial_year": 2024,
        "financial_year_start": "2024-01-01",
        "financial_year_end": "2024-12-31",
        "currency": "KES",
        "auditor_name": "Bridgehouse Certified Public Accountants",
        "turnover_cents": 50_000_000_00,
        "profit_after_tax_cents": 2_500_000_00,
        "total_assets_cents": 120_000_000_00,
        "cash_and_equivalents_cents": 8_000_000_00,
        "trade_payables_cents": 89_940_166,
        "extraction_method": "claude_sonnet_4_6",
        "_usage": {"input_tokens": 29_801, "output_tokens": 734},
    }


class _FakeAFRepo:
    """In-memory AuditedFinancialsRepo shared across instantiations (the endpoint
    constructs its own instance)."""

    _store: dict = {}

    @classmethod
    def reset(cls):
        cls._store = {}

    def get_by_deal_year(self, deal_id, financial_year):
        return self._store.get((deal_id, int(financial_year)))

    def upsert(self, data):
        key = (data["deal_id"], int(data["financial_year"]))
        existing = self._store.get(key, {})
        merged = {**existing, **data}
        merged.setdefault("id", "af-row-1")
        self._store[key] = merged
        return merged


class _ClaudeIngestionTestBase(unittest.TestCase):
    def setUp(self):
        _FakeAFRepo.reset()
        self.repos = build_memory_repos()
        self.app = FastAPI()
        self.app.state.repos_factory = lambda: self.repos
        self.app.include_router(v1_router)
        self.client = TestClient(self.app)

        self._repo_patch = patch(
            "backend.v1.db.supabase_repositories.AuditedFinancialsRepo",
            _FakeAFRepo,
        )
        self._repo_patch.start()
        self.addCleanup(self._repo_patch.stop)

        deal_resp = self.client.post("/v1/deals", data={"currency": "KES"})
        self.assertEqual(deal_resp.status_code, 200, deal_resp.text)
        self.deal_id = deal_resp.json()["deal"]["id"]

    def _upload(self, filename="financials.pdf"):
        return self.client.post(
            f"/v1/deals/{self.deal_id}/upload-financials",
            files={"file": (filename, io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            data={"declaration_type": "audited"},
        )


class TestClaudeIngestionRealFile(_ClaudeIngestionTestBase):
    def test_text_layer_audit_file_extracts_and_is_unconfirmed(self):
        with patch(
            "backend.v1.parsing.audited_financials_claude_extractor."
            "extract_audited_financials_claude",
            side_effect=_fake_text_layer_extraction,
        ):
            resp = self._upload("Kenlink Management Account Dec 2025.pdf")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        # Headline fields round-trip from the extraction.
        self.assertEqual(body["company_name"], "Kenlinks Limited")
        self.assertEqual(body["financial_year"], 2025)
        self.assertEqual(body["turnover_cents"], 20_790_711_00)
        self.assertEqual(body["profit_after_tax_cents"], 1_756_021_70)
        # Claude reports no confidence -> persisted as NULL, surfaced as null.
        self.assertIsNone(body["extraction_confidence"])

        # The stored row is unconfirmed, and the new-schema fields are persisted.
        row = _FakeAFRepo._store[(self.deal_id, 2025)]
        self.assertIsNone(row.get("confirmed_at"), "fresh upload must be unconfirmed")
        self.assertEqual(row["auditor_name"], "Some Auditor LLP")
        self.assertEqual(row["total_liabilities_cents"], 8_409_710)
        self.assertEqual(row["long_term_loans_cents"], 3_842_461)
        self.assertIsNotNone(row.get("loan_breakdown"))
        # Provenance is recorded as the Claude method, not the column's legacy
        # 'pdfplumber_coordinate' default.
        self.assertEqual(row["extraction_method"], "claude_sonnet_4_6")
        # The transient _usage block is never persisted as a column.
        self.assertNotIn("_usage", row)
        # A content sha256_hash is derived at the call site even though the
        # Claude extractor doesn't produce one.
        self.assertTrue(row.get("sha256_hash"))


class TestClaudeIngestionScannedPdf(_ClaudeIngestionTestBase):
    def test_scanned_pdf_with_no_confidence_still_succeeds(self):
        # The old path raised on this case (scanned -> confidence 0 -> 422).
        with patch(
            "backend.v1.parsing.audited_financials_claude_extractor."
            "extract_audited_financials_claude",
            side_effect=_fake_scanned_extraction,
        ):
            resp = self._upload("Tawi Fresh 2024 Audited Financial Statements.pdf")

        self.assertEqual(
            resp.status_code, 200,
            f"scanned-PDF extraction must succeed (no confidence==0 gate); got {resp.text}",
        )
        body = resp.json()
        self.assertEqual(body["company_name"], "Tawi Fresh Kenya Limited")
        self.assertEqual(body["financial_year"], 2024)
        self.assertIsNone(body["extraction_confidence"])

        row = _FakeAFRepo._store[(self.deal_id, 2024)]
        self.assertIsNone(row.get("confirmed_at"), "fresh upload must be unconfirmed")
        # currency present on the extraction is honoured.
        self.assertEqual(row["currency"], "KES")


class TestClaudeIngestionFailureDistinction(_ClaudeIngestionTestBase):
    """The 422 response distinguishes a transient rate-limit (retryable) from a
    genuine parse failure (unreadable document). The 429 -> 422 mapping was
    originally proven only by a live E2E curl (Maharaji hit the org rate limit);
    these tests pin it at the endpoint level so CI guards the distinction.
    """

    def test_rate_limit_returns_extraction_rate_limited(self):
        from backend.v1.parsing.audited_financials_claude_extractor import (
            ClaudeRateLimitError,
        )

        with patch(
            "backend.v1.parsing.audited_financials_claude_extractor."
            "extract_audited_financials_claude",
            side_effect=ClaudeRateLimitError("Claude API rate limit hit for 'x.pdf': 429"),
        ):
            resp = self._upload("x.pdf")

        self.assertEqual(resp.status_code, 422, resp.text)
        detail = resp.json()["detail"]
        # The new, distinct status — NOT the generic PARSE_FAILED.
        self.assertEqual(detail["status"], "EXTRACTION_RATE_LIMITED")
        self.assertNotEqual(detail["status"], "PARSE_FAILED")
        self.assertIn("retry", detail["detail"].lower())

    def test_genuine_parse_failure_still_returns_parse_failed(self):
        from backend.v1.parsing.audited_financials_claude_extractor import (
            ClaudeExtractionError,
        )

        with patch(
            "backend.v1.parsing.audited_financials_claude_extractor."
            "extract_audited_financials_claude",
            side_effect=ClaudeExtractionError("Claude response for 'x.pdf' was not valid JSON"),
        ):
            resp = self._upload("x.pdf")

        self.assertEqual(resp.status_code, 422, resp.text)
        detail = resp.json()["detail"]
        # Unreadable document — unchanged status.
        self.assertEqual(detail["status"], "PARSE_FAILED")


class TestExtractorRateLimitMapping(unittest.TestCase):
    """Extractor level: a real anthropic 429 maps to ClaudeRateLimitError (the
    type the endpoint keys EXTRACTION_RATE_LIMITED off), while other API errors
    stay ClaudeExtractionError. No network — the Anthropic client is mocked."""

    def test_anthropic_429_maps_to_rate_limit_error(self):
        import anthropic
        import httpx

        from backend.v1.parsing.audited_financials_claude_extractor import (
            extract_audited_financials_claude,
            ClaudeRateLimitError,
            ClaudeExtractionError,
        )

        resp = httpx.Response(
            429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )
        rate_limit_exc = anthropic.RateLimitError(
            "rate_limit_error: 30,000 input tokens per minute", response=resp, body=None
        )

        fake_client = MagicMock()
        fake_client.messages.create.side_effect = rate_limit_exc

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-not-real"}), patch(
            "backend.v1.parsing.audited_financials_claude_extractor.anthropic.Anthropic",
            return_value=fake_client,
        ):
            with self.assertRaises(ClaudeRateLimitError) as ctx:
                extract_audited_financials_claude(b"%PDF-1.4 fake", "x.pdf")

        # It IS a ClaudeExtractionError subclass (base-class handlers still catch
        # it), but the distinct subclass is what was raised.
        self.assertIsInstance(ctx.exception, ClaudeExtractionError)
        self.assertIs(type(ctx.exception), ClaudeRateLimitError)


if __name__ == "__main__":
    unittest.main()
