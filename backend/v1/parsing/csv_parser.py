import csv
import io
from typing import Any, Dict, List, Tuple

from .common import (
    REQUIRED_HEADERS,
    canonical_hash,
    compute_txn_id,
    normalize_descriptor,
    normalize_header,
    parse_amount_with_detection,
    parse_date,
    sort_rows,
)
from .errors import InvalidSchemaError


def parse_csv(file_bytes: bytes, document_id: str, deal_currency: str) -> Tuple[List[Dict[str, Any]], str, str]:
    text = file_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = {normalize_header(h) for h in (reader.fieldnames or [])}
    missing = REQUIRED_HEADERS - headers
    if missing:
        accepted = ", ".join(sorted(REQUIRED_HEADERS))
        raise InvalidSchemaError(
            f"Missing required columns: {', '.join(sorted(missing))}. "
            f"Accepted headers: {accepted}"
        )

    rows: List[Dict[str, Any]] = []
    currency_detection = "unknown"

    for idx, row in enumerate(reader, start=1):
        # normalize keys
        lowered = {normalize_header(k): v for k, v in row.items()}
        date_val = lowered.get("date")
        amount_val = lowered.get("amount")
        desc_val = lowered.get("description")
        direction_val = lowered.get("direction")
        # Prefer a real account column; otherwise fall back to the document id
        # (not "default") so transfer detection can pair inter-account flows — PAR-30.
        account_val = lowered.get("account_id") or lowered.get("account") or str(document_id)

        if desc_val in (None, ""):
            raise InvalidSchemaError(f"Description missing at row {idx}")

        try:
            signed_cents, detection = parse_amount_with_detection(amount_val, deal_currency)
            if detection == "ambiguous":
                currency_detection = "ambiguous"
        except InvalidSchemaError:
            raise
        except Exception as exc:
            raise InvalidSchemaError(str(exc)) from exc

        if direction_val:
            d = str(direction_val).strip().lower()
            if d in {"out", "debit", "withdrawal", "outflow"} and signed_cents > 0:
                signed_cents *= -1
            elif d in {"in", "credit", "inflow", "deposit"} and signed_cents < 0:
                signed_cents *= -1
            elif d not in {"out", "debit", "withdrawal", "outflow", "in", "credit", "inflow", "deposit"}:
                raise InvalidSchemaError(f"Invalid direction value at row {idx}: {direction_val}")

        txn_date = parse_date(date_val)

        row_obj: Dict[str, Any] = {
            "txn_date": txn_date,
            "signed_amount_cents": signed_cents,
            "abs_amount_cents": abs(signed_cents),
            "raw_descriptor": str(desc_val),
            "parsed_descriptor": str(desc_val).strip(),
            "normalized_descriptor": normalize_descriptor(desc_val),
            "account_id": str(account_val).strip(),
        }
        row_obj["txn_id"] = compute_txn_id(row_obj, document_id)
        rows.append(row_obj)

    if not rows:
        raise InvalidSchemaError("CSV contains no data rows")

    rows_sorted = sort_rows(rows)
    raw_hash = canonical_hash(rows_sorted)
    return rows_sorted, raw_hash, currency_detection
