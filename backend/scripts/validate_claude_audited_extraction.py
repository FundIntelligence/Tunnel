"""
One-off validation runner for audited_financials_claude_extractor.py.

Runs the new Claude-based extractor against the 6 real audited-financials /
management-account files available to this team (the Buildex repo fixture
plus the 5-file corpus in ~/Documents/Parity/Pilot & Demo/Auditfilestraining/),
and dumps the raw JSON result + token usage for each to
scripts/validate_claude_audited_extraction_output/.

Not part of the production codebase. See
Tunnel/docs/AUDITED_FINANCIALS_EXTRACTION_INVESTIGATION.md section 9 for
the analysis built from this script's output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # backend/

from v1.parsing.audited_financials_claude_extractor import (  # noqa: E402
    ClaudeExtractionError,
    extract_audited_financials_claude,
)

_TRAINING_DIR = Path.home() / "Documents" / "Parity" / "Pilot & Demo" / "Auditfilestraining"
_BUILDEX_FIXTURE = (
    _HERE.parents[2] / "parity-ingestion" / "tests" / "fixtures" / "buildex" / "buildex_financials_2025.pdf"
)
_OUTPUT_DIR = _HERE.parent / "validate_claude_audited_extraction_output"

FILES = [
    _BUILDEX_FIXTURE,
    _TRAINING_DIR / "Kenlink Management Account Dec 2025.pdf",
    _TRAINING_DIR / "Tawi Fresh 2024 Audited Financial Statements.pdf",
    _TRAINING_DIR / "Paragon Feeds Ltd Financials 2026 (2).pdf",
    _TRAINING_DIR / "Maharaji Audited Accounts.pdf",
    _TRAINING_DIR / "Tres Beau Ltd Audited Accounts.pdf",
]

# Sonnet 4.6 pricing: $3.00 / 1M input tokens, $15.00 / 1M output tokens.
_INPUT_RATE_PER_TOKEN = 3.00 / 1_000_000
_OUTPUT_RATE_PER_TOKEN = 15.00 / 1_000_000


def main() -> None:
    _OUTPUT_DIR.mkdir(exist_ok=True)
    summary = []

    for path in FILES:
        print(f"\n=== {path.name} ===")
        if not path.exists():
            print(f"  MISSING: {path}")
            summary.append({"file": path.name, "error": "file not found"})
            continue

        file_bytes = path.read_bytes()
        try:
            result = extract_audited_financials_claude(file_bytes, path.name)
        except ClaudeExtractionError as exc:
            print(f"  EXTRACTION FAILED: {exc}")
            summary.append({"file": path.name, "error": str(exc)})
            continue

        usage = result.pop("_usage")
        cost = (
            usage["input_tokens"] * _INPUT_RATE_PER_TOKEN
            + usage["output_tokens"] * _OUTPUT_RATE_PER_TOKEN
        )
        out_path = _OUTPUT_DIR / f"{path.stem}.json"
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True))

        print(f"  company_name: {result.get('company_name')}")
        print(f"  financial_year: {result.get('financial_year')}")
        print(f"  currency: {result.get('currency')}")
        print(f"  input_tokens={usage['input_tokens']} output_tokens={usage['output_tokens']} cost=${cost:.4f}")
        print(f"  written: {out_path}")

        summary.append(
            {
                "file": path.name,
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "cost_usd": round(cost, 4),
                "output_json": str(out_path),
            }
        )

    summary_path = _OUTPUT_DIR / "_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\n=== summary written to {summary_path} ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
