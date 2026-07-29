import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

from ..core.snapshot_engine import decode_snapshot_row
from .repositories import (
    AnalysisRunsRepository,
    ClassificationOverridesRepository,
    CustomFlagsRepository,
    DealsRepository,
    DocumentsRepository,
    EnrichmentsRepository,
    EntitiesRepository,
    RawTransactionsRepository,
    SnapshotsRepository,
    TxnEntityMapRepository,
    TransferLinksRepository,
    OverridesRepository,
)
from .supabase_client import get_supabase

logger = logging.getLogger(__name__)

# PostgREST often caps a single response at ~1000 rows (Supabase API default). Requesting
# a huge limit in one call still returns at most that cap — so we must paginate.
_SELECT_PAGE_SIZE = 1000
SELECT_ROW_LIMIT = 50_000


class BaseRepo:
    def __init__(self, table: str, client_timeout: Optional[float] = None):
        self.client = get_supabase(timeout=client_timeout)
        self.table = table

    def insert(self, data: Dict[str, Any]) -> Dict[str, Any]:
        res = self.client.table(self.table).insert(data).execute()
        return res.data[0] if res.data else data

    def insert_many(self, data: Iterable[Dict[str, Any]]) -> None:
        items = list(data)
        if not items:
            return
        self.client.table(self.table).insert(items).execute()

    def select_eq(self, column: str, value: Any, order_by: str = "id") -> List[Dict[str, Any]]:
        # Paginate: one .range(0, N) with a large N still hits the server max (~1000 rows).
        # An .order() is required for .range() to paginate correctly: without a stable
        # sort, Postgres is free to return rows in a different order on each page request,
        # so consecutive .range() calls can return the same row twice (or skip one) —
        # confirmed live on parity-staging where this silently duplicated a raw transaction
        # across two pages and blew up the downstream ON CONFLICT upsert in
        # export_persist_deal_state with "cannot affect row a second time". Defaults to
        # "id" (present on nearly every table here); pass order_by explicitly for the
        # handful of tables without an id column (e.g. pds_entities, pds_txn_entity_map).
        out: List[Dict[str, Any]] = []
        offset = 0
        while True:
            end = offset + _SELECT_PAGE_SIZE - 1
            res = (
                self.client.table(self.table)
                .select("*")
                .eq(column, value)
                .order(order_by)
                .range(offset, end)
                .execute()
            )
            chunk = res.data or []
            out.extend(chunk)
            if len(chunk) < _SELECT_PAGE_SIZE:
                break
            offset += _SELECT_PAGE_SIZE
            if offset > 2_000_000:
                logger.warning(
                    "select_eq pagination exceeded 2M rows (table=%s %s=...)",
                    self.table,
                    column,
                )
                break
        return out

    def select_eq2(
        self, col1: str, val1: Any, col2: str, val2: Any, order_by: str = "id"
    ) -> List[Dict[str, Any]]:
        """Same pagination as select_eq, with a second equality filter pushed to the DB."""
        out: List[Dict[str, Any]] = []
        offset = 0
        while True:
            end = offset + _SELECT_PAGE_SIZE - 1
            res = (
                self.client.table(self.table)
                .select("*")
                .eq(col1, val1)
                .eq(col2, val2)
                .order(order_by)
                .range(offset, end)
                .execute()
            )
            chunk = res.data or []
            out.extend(chunk)
            if len(chunk) < _SELECT_PAGE_SIZE:
                break
            offset += _SELECT_PAGE_SIZE
            if offset > 2_000_000:
                break
        return out

    def select_in(self, column: str, values: Sequence[Any]) -> List[Dict[str, Any]]:
        """Fetch only rows matching a specific set of ids — avoids pulling an entire
        deal's table just to look up a handful of referenced rows."""
        ids = [v for v in dict.fromkeys(values) if v]
        if not ids:
            return []
        out: List[Dict[str, Any]] = []
        for i in range(0, len(ids), BATCH_SIZE):
            chunk_ids = ids[i : i + BATCH_SIZE]
            res = self.client.table(self.table).select("*").in_(column, chunk_ids).execute()
            out.extend(res.data or [])
        return out

    def delete_eq(self, column: str, value: Any) -> None:
        self.client.table(self.table).delete().eq(column, value).execute()


class DealsRepo(DealsRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_deals")

    def create_deal(self, deal: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert(deal)

    def get_deal(self, deal_id: str) -> Optional[Dict[str, Any]]:
        rows = self.select_eq("id", deal_id)
        return rows[0] if rows else None

    def list_deals(self, created_by: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("created_by", created_by)

    def set_currency_if_unset(self, deal_id: str, currency: str) -> None:
        """
        Sets currency on pds_deals from the first real document detection.
        currency_source distinguishes a creation-time placeholder ('default') from
        a confirmed detection ('detected') — once 'detected', never auto-corrected
        again, regardless of which currency code is sitting in the column.
        """
        deal = self.get_deal(deal_id)
        if not deal:
            return
        if deal.get("currency_source", "default") == "detected":
            return
        self.client.table(self.table).update({
            "currency": currency,
            "currency_source": "detected",
        }).eq("id", deal_id).execute()


class DocumentsRepo(DocumentsRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_documents")

    def create_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert(document)

    def get_batch_upload_count(self, deal_id: str) -> int:
        """Distinct batch_number count for a deal (RPC when available, else local count)."""
        try:
            res = self.client.rpc(
                "get_deal_batch_count", {"p_deal_id": deal_id}
            ).execute()
            d = res.data
            if d is None:
                return 0
            if isinstance(d, int):
                return d
            if isinstance(d, list):
                if not d:
                    return 0
                x = d[0]
                if isinstance(x, dict):
                    return int(next(iter(x.values())))
                return int(x)
            return int(d)
        except Exception as exc:
            logger.warning(
                "get_deal_batch_count RPC failed for deal %s: %s", deal_id, exc
            )
            rows = self.list_by_deal(deal_id)
            batches = {
                r.get("batch_number")
                for r in rows
                if r.get("batch_number") is not None
            }
            return len(batches)

    def update_status(
        self,
        document_id: str,
        status: str,
        *,
        currency_mismatch: bool = False,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
        error_stage: Optional[str] = None,
        next_action: Optional[str] = None,
        analytics: Optional[Dict[str, Any]] = None,
        currency_detected: Optional[str] = None,
    ) -> None:
        data: Dict[str, Any] = {"status": status, "currency_mismatch": currency_mismatch}
        if error_message is not None:
            data["error_message"] = error_message
        if error_type is not None:
            data["error_type"] = error_type
        if error_stage is not None:
            data["error_stage"] = error_stage
        if next_action is not None:
            data["next_action"] = next_action
        if analytics is not None:
            data["analytics"] = analytics
        if currency_detected is not None:
            data["currency_detected"] = currency_detected
        self.client.table(self.table).update(data).eq("id", document_id).execute()

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        rows = self.select_eq("id", document_id)
        return rows[0] if rows else None

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)

    def get_latest_update_at(self, deal_id: str) -> Optional[str]:
        rows = self.select_eq("deal_id", deal_id)
        if not rows:
            return None
        return max((r.get("created_at") or "") for r in rows)

    def delete_document(self, document_id: str) -> None:
        self.delete_eq("id", document_id)


BATCH_SIZE = 1000


class RawTxRepo(RawTransactionsRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_raw_transactions")

    def insert_batch(self, rows: Iterable[Dict[str, Any]]) -> None:
        items = list(rows)
        if not items:
            return
        for i in range(0, len(items), BATCH_SIZE):
            batch = items[i : i + BATCH_SIZE]
            self.client.table(self.table).insert(batch).execute()

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)

    def list_by_document(self, document_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("document_id", document_id)

    def get_by_deal_and_id(self, deal_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        """PAR-96: point lookup for a single raw transaction, instead of
        list_by_deal(deal_id) + a Python scan over the whole deal."""
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("deal_id", deal_id)
            .eq("id", row_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def get_all_transactions_for_export(
        self, deal_id: str, year: Optional[int] = None
    ) -> Sequence[Dict[str, Any]]:
        """Fetch all transactions with document/entity context for CSV export."""
        docs_res = (
            self.client.table("pds_documents")
            .select("id,name,storage_url")
            .eq("deal_id", deal_id)
            .range(0, SELECT_ROW_LIMIT - 1)
            .execute()
        )
        docs = docs_res.data or []
        if not docs:
            return []

        doc_ids = [d.get("id") for d in docs if d.get("id")]
        if not doc_ids:
            return []
        doc_by_id = {d["id"]: d for d in docs if d.get("id")}

        tx_rows: List[Dict[str, Any]] = []
        offset = 0
        while True:
            end = offset + SELECT_ROW_LIMIT - 1
            q = (
                self.client.table(self.table)
                .select("id,txn_id,txn_date,description,debit_cents,credit_cents,document_id")
                .in_("document_id", doc_ids)
                .range(offset, end)
            )
            if year is not None:
                q = q.gte("txn_date", f"{year:04d}-01-01").lte("txn_date", f"{year:04d}-12-31")
            res = q.execute()
            chunk = res.data or []
            tx_rows.extend(chunk)
            if len(chunk) < SELECT_ROW_LIMIT:
                break
            offset += SELECT_ROW_LIMIT

        if not tx_rows:
            return []

        tx_ids = [t.get("txn_id") for t in tx_rows if t.get("txn_id")]
        tx_map_by_txn_id: Dict[str, Dict[str, Any]] = {}
        if tx_ids:
            map_res = (
                self.client.table("pds_txn_entity_map")
                .select("txn_id,entity_id,role")
                .eq("deal_id", deal_id)
                .in_("txn_id", tx_ids)
                .range(0, SELECT_ROW_LIMIT - 1)
                .execute()
            )
            for m in (map_res.data or []):
                tid = m.get("txn_id")
                if tid and tid not in tx_map_by_txn_id:
                    tx_map_by_txn_id[tid] = m

        entity_ids = [m.get("entity_id") for m in tx_map_by_txn_id.values() if m.get("entity_id")]
        entity_name_by_id: Dict[str, str] = {}
        if entity_ids:
            entity_res = (
                self.client.table("pds_entities")
                .select("entity_id,display_name")
                .eq("deal_id", deal_id)
                .in_("entity_id", entity_ids)
                .range(0, SELECT_ROW_LIMIT - 1)
                .execute()
            )
            entity_name_by_id = {
                e.get("entity_id"): e.get("display_name") or ""
                for e in (entity_res.data or [])
                if e.get("entity_id")
            }

        merged: List[Dict[str, Any]] = []
        for tx in tx_rows:
            tx_tid = tx.get("txn_id")
            mapped = tx_map_by_txn_id.get(tx_tid) if tx_tid else None
            entity_id = mapped.get("entity_id") if mapped else None
            doc = doc_by_id.get(tx.get("document_id"))
            merged.append(
                {
                    "txn_date": tx.get("txn_date") or "",
                    "description": tx.get("description") or "",
                    "debit_cents": tx.get("debit_cents") or 0,
                    "credit_cents": tx.get("credit_cents") or 0,
                    "role": (mapped or {}).get("role") or "",
                    "entity_name": entity_name_by_id.get(entity_id or "", ""),
                    "source_file": (doc or {}).get("name")
                    or (doc or {}).get("storage_url")
                    or "",
                    "document_id": tx.get("document_id") or "",
                }
            )

        merged.sort(key=lambda r: (str(r.get("txn_date") or ""), str(r.get("description") or "")))
        return merged


class TransferLinksRepo(TransferLinksRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_transfer_links")

    def insert_batch(self, links: Iterable[Dict[str, Any]]) -> None:
        items = list(links)
        if not items:
            return
        for i in range(0, len(items), BATCH_SIZE):
            batch = items[i : i + BATCH_SIZE]
            self.client.table(self.table).insert(batch).execute()

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)


class EntitiesRepo(EntitiesRepository, BaseRepo):
    # 2026-07-23: bulk upsert on this table hit the default 120s postgrest
    # client timeout during a live demo export (deal 2A619980-0F74-4D).
    # Did not reproduce on repeated on-demand re-runs, so treated as a
    # transient/load-related window rather than a structural batch-size
    # problem — raised timeout + added one retry as cheap insurance.
    _UPSERT_TIMEOUT_SECONDS = 300

    def __init__(self):
        super().__init__("pds_entities", client_timeout=self._UPSERT_TIMEOUT_SECONDS)

    def upsert_entities(self, entities: Iterable[Dict[str, Any]]) -> None:
        items = list(entities)
        if not items:
            return
        for i in range(0, len(items), BATCH_SIZE):
            batch = items[i : i + BATCH_SIZE]
            try:
                self.client.table(self.table).upsert(batch).execute()
            except (httpx.TimeoutException, httpx.ReadTimeout):
                logger.warning(
                    "[EntitiesRepo] upsert batch timed out, retrying once (batch_size=%d)",
                    len(batch),
                )
                time.sleep(2)
                self.client.table(self.table).upsert(batch).execute()

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        # pds_entities has no "id" column (PK is entity_id) — order by that instead
        # of select_eq's "id" default.
        return self.select_eq("deal_id", deal_id, order_by="entity_id")


class TxnEntityMapRepo(TxnEntityMapRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_txn_entity_map")

    def upsert_mappings(self, mappings: Iterable[Dict[str, Any]]) -> None:
        items = list(mappings)
        if not items:
            return
        for i in range(0, len(items), BATCH_SIZE):
            batch = items[i : i + BATCH_SIZE]
            self.client.table(self.table).upsert(batch).execute()

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        # pds_txn_entity_map has no "id" column (PK is txn_id) — order by that
        # instead of select_eq's "id" default.
        return self.select_eq("deal_id", deal_id, order_by="txn_id")

    def list_needs_review_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        """Filters role='needs_review' in the DB query instead of pulling every
        mapping row for the deal and filtering in Python."""
        return self.select_eq2("deal_id", deal_id, "role", "needs_review", order_by="txn_id")

    def update_role(self, txn_uuid: str, new_role: str) -> None:
        self.client.table(self.table).update({"role": new_role}).eq("txn_id", txn_uuid).execute()

    def count_needs_review(self, deal_id: str) -> int:
        rows = self.select_eq("deal_id", deal_id, order_by="txn_id")
        return sum(1 for r in rows if (r.get("role") or "") == "needs_review")

    def get_by_deal_and_txn(self, deal_id: str, txn_id: str) -> Optional[Dict[str, Any]]:
        """PAR-96: point lookup for a single txn_map row, instead of
        list_by_deal(deal_id) + a Python scan over the whole deal."""
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("deal_id", deal_id)
            .eq("txn_id", txn_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def count_needs_review_excluding(self, deal_id: str, exclude_txn_id: str) -> int:
        """PAR-96: DB-side COUNT for the post-resolve remaining-count, instead of
        list_by_deal(deal_id) + a Python scan over the whole deal. Same semantics
        as the resolve_transaction() call site it replaces: role == 'needs_review'
        (already lowercase in the DB, per the equivalent DB-side filter in
        list_needs_review_by_deal above) excluding the just-resolved row.

        PAR-96 hotfix: originally used .select("*", count="exact", head=True) —
        confirmed live against parity-staging (2026-08-04, postgrest-py 0.17.2)
        that head=True silently makes res.count come back 0 regardless of the
        actual count, even though the identical query without head=True returns
        the correct count. Not caught locally because the in-memory test double
        doesn't exercise real PostgREST HTTP/count semantics at all, and the one
        existing test asserting remaining_count happened to expect 0 anyway in
        its fixture (a coincidental false-positive, not a real check). Dropping
        head=True and projecting only txn_id (not "*") keeps this far cheaper
        than the original full-deal scan it replaced, without the broken
        HEAD-request path."""
        res = (
            self.client.table(self.table)
            .select("txn_id", count="exact")
            .eq("deal_id", deal_id)
            .eq("role", "needs_review")
            .neq("txn_id", exclude_txn_id)
            .execute()
        )
        return res.count or 0


class ExportPersistenceRepo(BaseRepo):
    """PAR-95: wraps export()'s delete+reinsert of pds_txn_entity_map/links/
    entities/pds_analysis_runs in a single .rpc() call to the
    export_persist_deal_state Postgres function (migration 026), so the whole
    sequence commits or rolls back as one DB transaction instead of four
    separate PostgREST calls. See that migration for the exact delete/insert
    semantics it replicates."""

    def __init__(self):
        # No single table backs this repo — it only needs self.client for
        # .rpc(). "pds_analysis_runs" is an arbitrary anchor table.
        super().__init__("pds_analysis_runs")

    def persist_deal_state(
        self,
        *,
        deal_id: str,
        run: Dict[str, Any],
        links: Iterable[Dict[str, Any]],
        entities: Iterable[Dict[str, Any]],
        txn_map: Iterable[Dict[str, Any]],
    ) -> None:
        self.client.rpc(
            "export_persist_deal_state",
            {
                "p_deal_id": deal_id,
                "p_run": run,
                "p_links": list(links),
                "p_entities": list(entities),
                "p_txn_map": list(txn_map),
            },
        ).execute()


class OverrideLogRepo(BaseRepo):
    def __init__(self):
        super().__init__("pds_override_log")

    def insert_log(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert(entry)

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)

    def get_latest_update_at(self, deal_id: str) -> Optional[str]:
        """PAR-111: export()'s short-circuit freshness check needs this to
        notice a fresh Review Queue resolution — see OverridesRepo.get_latest_update_at
        for the sibling check on pds_overrides (a genuinely different, still-live
        table: entity-level classification overrides fed into run_pipeline(),
        vs. this table's per-transaction resolve_transaction() audit log,
        overlaid onto run_pipeline()'s output afterward per PAR-77). Both can
        invalidate a cached export, so the freshness check must take the max
        of both, not just one."""
        rows = self.select_eq("deal_id", deal_id)
        if not rows:
            return ""
        return max((r.get("created_at") or "") for r in rows)


class IntelligenceLogRepo(BaseRepo):
    def __init__(self):
        super().__init__("pds_intelligence_log")

    def insert_log(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert(entry)

    def mark_logged(self, entry_id: str) -> None:
        self.client.table(self.table).update({"is_logged": True}).eq("id", entry_id).execute()

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)


class ReviewThresholdLogRepo(BaseRepo):
    """
    PAR-89 part B: append-only diagnostics log for the large-positive-credit
    review-threshold heuristic (median/mad/threshold/ratio per flagged txn).
    Deliberately write-once — no update method. Callers must wrap writes in
    try/except (see api.py's export flow) — this table is never read back by
    the pipeline and a write failure must not affect classification/export.
    """

    def __init__(self):
        super().__init__("pds_review_threshold_log")

    def insert_log_many(self, entries: Iterable[Dict[str, Any]]) -> None:
        self.insert_many(entries)


class OverridesRepo(OverridesRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_overrides")

    def insert_override(self, override: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert(override)

    def list_overrides(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)

    def get_latest_update_at(self, deal_id: str) -> Optional[str]:
        rows = self.select_eq("deal_id", deal_id)
        if not rows:
            return ""
        return max((r.get("created_at") or "") for r in rows)


class AnalysisRunsRepo(AnalysisRunsRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_analysis_runs")

    def insert_run(self, run: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert(run)

    def list_runs(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)

    def get_latest_run(self, deal_id: str) -> Optional[Dict[str, Any]]:
        rows = self.select_eq("deal_id", deal_id)
        if not rows:
            return None
        return max(rows, key=lambda r: r.get("created_at") or "")

    def update_reconciliation(self, run_id: str, status: str, pct_bp: Optional[int]) -> None:
        self.client.table(self.table).update(
            {"reconciliation_status": status, "reconciliation_pct_bp": pct_bp}
        ).eq("id", run_id).execute()


class SnapshotsRepo(SnapshotsRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_snapshots")

    def insert_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.get_by_hash(snapshot.get("sha256_hash", ""))
        if existing:
            return existing
        inserted = self.insert(snapshot)
        return decode_snapshot_row(inserted) or inserted

    def get_by_hash(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        rows = self.select_eq("sha256_hash", sha256_hash)
        if not rows:
            return None
        return decode_snapshot_row(rows[0])

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        rows = self.select_eq("id", snapshot_id)
        if not rows:
            return None
        return decode_snapshot_row(rows[0])

    # Every column on pds_snapshots EXCEPT canonical_json. canonical_json is a
    # multi-MB blob (~4.5 MB/row); selecting it for list/aggregate reads pushes the
    # query past the 8s authenticated-role statement_timeout and PostgREST returns
    # 500 (PAR-33). List/metadata consumers never read it, so we never fetch it here.
    _METADATA_COLUMNS = (
        "id, deal_id, analysis_run_id, schema_version, config_version, "
        "sha256_hash, created_by, created_at, financial_state_hash"
    )

    def list_snapshots(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        # Metadata only — no canonical_json. Callers (GET /deals/{id},
        # GET /deals/{id}/snapshots) return this list to the UI, which renders
        # hashes/dates, not the canonical payload. Pulling canonical_json here is
        # what made the deals list 500 under concurrent per-deal fetches.
        rows = (
            self.client.table(self.table)
            .select(self._METADATA_COLUMNS)
            .eq("deal_id", deal_id)
            .order("created_at", desc=True)
            .execute()
        )
        return rows.data or []

    def get_latest_snapshot(self, deal_id: str) -> Optional[Dict[str, Any]]:
        # Fetch exactly the latest row at the DB (uses idx_pds_snapshots_deal on
        # (deal_id, created_at DESC)) instead of pulling every snapshot row and
        # taking max() in Python. A 2-snapshot deal was ~9 MB over the wire and
        # blew the 8s statement_timeout; this is a single ~4.5 MB row. canonical_json
        # is kept because the heavy consumers (PDF render, enrichment, analytics,
        # parity-review) read it.
        rows = (
            self.client.table(self.table)
            .select("*")
            .eq("deal_id", deal_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        data = rows.data or []
        if not data:
            return None
        return decode_snapshot_row(data[0])

    def get_all_snapshots_for_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        # For snapshots, don't paginate - there are only a few per deal
        # Explicitly select canonical_json to ensure it's included
        rows = (
            self.client.table(self.table)
            .select("id, deal_id, analysis_run_id, canonical_json, sha256_hash, financial_state_hash, created_at, schema_version, config_version")
            .eq("deal_id", deal_id)
            .order("created_at", desc=False)
            .execute()
        )
        decoded = [decode_snapshot_row(r) or r for r in (rows.data or [])]
        return sorted(decoded, key=lambda r: r.get("created_at") or "")


class EnrichmentsRepo(EnrichmentsRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_snapshot_enrichments")

    def insert_enrichment(self, enrichment: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert(enrichment)

    def get_by_hash(self, enriched_hash: str) -> Optional[Dict[str, Any]]:
        rows = self.select_eq("enriched_hash", enriched_hash)
        return rows[0] if rows else None

    def get_enrichment(self, enrichment_id: str) -> Optional[Dict[str, Any]]:
        rows = self.select_eq("id", enrichment_id)
        return rows[0] if rows else None

    def get_latest_for_snapshot(self, base_snapshot_id: str) -> Optional[Dict[str, Any]]:
        rows = self.select_eq("base_snapshot_id", base_snapshot_id)
        if not rows:
            return None
        return max(rows, key=lambda r: r.get("created_at") or "")

    def list_for_snapshot(self, base_snapshot_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("base_snapshot_id", base_snapshot_id)

    def mark_final(self, enrichment_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table(self.table)
            .update({"is_final": True})
            .eq("id", enrichment_id)
            .execute()
        )
        return res.data[0] if res.data else None


class ClassificationOverridesRepo(ClassificationOverridesRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_classification_overrides")

    def insert_batch(self, records: Iterable[Dict[str, Any]]) -> None:
        self.insert_many(records)

    def list_by_enrichment(self, enrichment_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("enrichment_id", enrichment_id)


class CustomFlagsRepo(CustomFlagsRepository, BaseRepo):
    def __init__(self):
        super().__init__("pds_custom_flags")

    def insert_batch(self, records: Iterable[Dict[str, Any]]) -> None:
        self.insert_many(records)

    def list_by_enrichment(self, enrichment_id: str) -> Sequence[Dict[str, Any]]:
        return self.select_eq("enrichment_id", enrichment_id)


class AuditedFinancialsRepo(BaseRepo):
    def __init__(self):
        super().__init__("pds_audited_financials")

    def upsert(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update on (deal_id, financial_year) unique constraint."""
        res = (
            self.client.table(self.table)
            .upsert(data, on_conflict="deal_id,financial_year")
            .execute()
        )
        return res.data[0] if res.data else data

    def get_by_deal_id(self, deal_id: str) -> List[Dict[str, Any]]:
        """Active (non-removed) records for a deal. Soft-removed rows
        (removed_at IS NOT NULL) are retained for audit but never read."""
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("deal_id", deal_id)
            .is_("removed_at", "null")
            .execute()
        )
        return res.data or []

    def get_by_deal_year(self, deal_id: str, financial_year: int) -> Optional[Dict[str, Any]]:
        """Return the single ACTIVE row for (deal_id, financial_year), or None.
        Soft-removed rows are excluded so a removed FY does not block a re-upload
        via the 409 guard and is not re-removed via the DELETE route."""
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("deal_id", deal_id)
            .eq("financial_year", financial_year)
            .is_("removed_at", "null")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def soft_delete(
        self,
        deal_id: str,
        financial_year: int,
        removed_at: str,
        removed_reason: Optional[str],
        removed_by: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Mark the active (deal_id, financial_year) row removed. Returns the
        updated row, or None if there was no active row to remove (already
        removed, or lost a race with a concurrent re-upload). Soft-delete only —
        the row is retained; reads filter it out via removed_at IS NULL."""
        res = (
            self.client.table(self.table)
            .update({
                "removed_at": removed_at,
                "removed_reason": removed_reason,
                "removed_by": removed_by,
            })
            .eq("deal_id", deal_id)
            .eq("financial_year", financial_year)
            .is_("removed_at", "null")
            .execute()
        )
        return res.data[0] if res.data else None

    def patch_coverage_summary(self, deal_id: str, financial_year: int, summary: Dict[str, Any]) -> None:
        self.client.table(self.table).update(summary).eq("deal_id", deal_id).eq("financial_year", financial_year).execute()


class AfConfirmLogRepo(BaseRepo):
    """Append-only audit trail of audited-financials confirmation events
    (one row per confirm: who/when/which FY). Insert-only by convention —
    no update/delete, mirroring the override-log posture."""

    def __init__(self):
        super().__init__("pds_af_confirm_log")

    def insert_log(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert(entry)

    def list_by_deal(self, deal_id: str) -> List[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)


class AccountCoverageRepo(BaseRepo):
    def __init__(self):
        super().__init__("pds_account_coverage")

    def replace_for_deal(self, deal_id: str, rows: List[Dict[str, Any]]) -> None:
        """Delete existing rows for the deal then insert fresh ones."""
        self.client.table(self.table).delete().eq("deal_id", deal_id).execute()
        if rows:
            self.insert_many(rows)

    def list_by_deal(self, deal_id: str) -> List[Dict[str, Any]]:
        return self.select_eq("deal_id", deal_id)
