import io
from typing import Any, Dict, List, Tuple

import pdfplumber

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


def _find_table_with_headers(tables: List[List[List[Any]]]) -> List[List[Any]]:
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = [normalize_header(h) for h in table[0]]
        if REQUIRED_HEADERS.issubset(set(header)):
            return table
    return []


def parse_pdf(file_bytes: bytes, document_id: str, deal_currency: str) -> Tuple[List[Dict[str, Any]], str, str]:
    rows: List[Dict[str, Any]] = []
    currency_detection = "unknown"

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            table = _find_table_with_headers(tables or [])
            if not table:
                continue
            header = [normalize_header(h) for h in table[0]]
            header_index = {name: idx for idx, name in enumerate(header)}

            for row in table[1:]:
                # skip empty rows
                if not row or all(cell in (None, "") for cell in row):
                    continue

                date_val = row[header_index["date"]] if header_index.get("date") is not None else None
                amount_val = row[header_index["amount"]] if header_index.get("amount") is not None else None
                desc_val = row[header_index["description"]] if header_index.get("description") is not None else None
                direction_val = None
                if "direction" in header_index:
                    direction_val = row[header_index["direction"]]

                if desc_val in (None, ""):
                    raise InvalidSchemaError("Description missing in PDF row")

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
                        raise InvalidSchemaError(f"Invalid direction value in PDF row: {direction_val}")

                txn_date = parse_date(date_val)

                row_obj: Dict[str, Any] = {
                    "txn_date": txn_date,
                    "signed_amount_cents": signed_cents,
                    "abs_amount_cents": abs(signed_cents),
                    "raw_descriptor": str(desc_val),
                    "parsed_descriptor": str(desc_val).strip(),
                    "normalized_descriptor": normalize_descriptor(desc_val),
                    # account_id must differ per source document so transfer
                    # detection (match_transfers) can pair inter-account flows.
                    # Was hardcoded "default" — see PAR-30.
                    "account_id": str(document_id),
                }
                row_obj["txn_id"] = compute_txn_id(row_obj, document_id)
                rows.append(row_obj)

    if not rows:
        raise InvalidSchemaError("No valid table with required headers found in PDF")

    rows_sorted = sort_rows(rows)
    raw_hash = canonical_hash(rows_sorted)
    return rows_sorted, raw_hash, currency_detection
