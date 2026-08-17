"""
In-memory repository implementations for CI/test use.
No external dependencies (no Supabase, no SQLite).
"""

import copy
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..core.snapshot_engine import decode_snapshot_row

from .repositories import (
    AnalysisRunsRepository,
    DealsRepository,
    DocumentsRepository,
    EntitiesRepository,
    OverridesRepository,
    RawTransactionsRepository,
    SnapshotsRepository,
    TransferLinksRepository,
    TxnEntityMapRepository,
)


class MemoryDealsRepo(DealsRepository):
    def __init__(self):
        self._store: List[Dict[str, Any]] = []

    def create_deal(self, deal: Dict[str, Any]) -> Dict[str, Any]:
        row = {**deal, "created_at": deal.get("created_at") or datetime.utcnow().isoformat()}
        self._store.append(row)
        return copy.deepcopy(row)

    def get_deal(self, deal_id: str) -> Optional[Dict[str, Any]]:
        for d in self._store:
            if d["id"] == deal_id:
                return copy.deepcopy(d)
        return None

    def list_deals(self, created_by: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(d) for d in self._store if d.get("created_by") == created_by]


class MemoryDocumentsRepo(DocumentsRepository):
    def __init__(self):
        self._store: List[Dict[str, Any]] = []

    def create_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        row = {**document, "created_at": document.get("created_at") or datetime.utcnow().isoformat()}
        self._store.append(row)
        return copy.deepcopy(row)

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
        for d in self._store:
            if d["id"] == document_id:
                d["status"] = status
                d["currency_mismatch"] = currency_mismatch
                if error_message is not None:
                    d["error_message"] = error_message
                if error_type is not None:
                    d["error_type"] = error_type
                if error_stage is not None:
                    d["error_stage"] = error_stage
                if next_action is not None:
                    d["next_action"] = next_action
                if analytics is not None:
                    d["analytics"] = analytics
                if currency_detected is not None:
                    d["currency_detected"] = currency_detected
                break

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(d) for d in self._store if d.get("deal_id") == deal_id]

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        for d in self._store:
            if d["id"] == document_id:
                return copy.deepcopy(d)
        return None

    def get_latest_update_at(self, deal_id: str) -> Optional[str]:
        rows = [d for d in self._store if d.get("deal_id") == deal_id]
        if not rows:
            return None
        return max((r.get("created_at") or "") for r in rows)

    def delete_document(self, document_id: str) -> None:
        self._store = [d for d in self._store if d["id"] != document_id]


class MemoryRawTxRepo(RawTransactionsRepository):
    def __init__(self):
        self._store: List[Dict[str, Any]] = []

    def insert_batch(self, rows: Iterable[Dict[str, Any]]) -> None:
        for r in rows:
            # Mirrors the real schema's `id uuid primary key default
            # gen_random_uuid()` (pds_raw_transactions) — a real INSERT gets
            # this for free from Postgres; the in-memory double needs to
            # simulate it explicitly or every row stays id-less forever.
            row = copy.deepcopy(r)
            row.setdefault("id", str(uuid.uuid4()))
            self._store.append(row)

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(r) for r in self._store if r.get("deal_id") == deal_id]

    def list_by_document(self, document_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(r) for r in self._store if r.get("document_id") == document_id]

    def select_in(self, column: str, values) -> Sequence[Dict[str, Any]]:
        wanted = set(values)
        return [copy.deepcopy(r) for r in self._store if r.get(column) in wanted]

    def get_by_deal_and_id(self, deal_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        for r in self._store:
            if r.get("deal_id") == deal_id and str(r.get("id")) == str(row_id):
                return copy.deepcopy(r)
        return None


class MemoryTransferLinksRepo(TransferLinksRepository):
    def __init__(self):
        self._store: List[Dict[str, Any]] = []

    def insert_batch(self, links: Iterable[Dict[str, Any]]) -> None:
        for lnk in links:
            self._store.append(copy.deepcopy(lnk))

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(l) for l in self._store if l.get("deal_id") == deal_id]

    def delete_eq(self, column: str, value: Any) -> None:
        self._store = [l for l in self._store if l.get(column) != value]


class MemoryEntitiesRepo(EntitiesRepository):
    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}

    def upsert_entities(self, entities: Iterable[Dict[str, Any]]) -> None:
        for e in entities:
            self._store[e["entity_id"]] = copy.deepcopy(e)

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(e) for e in self._store.values() if e.get("deal_id") == deal_id]

    def select_in(self, column: str, values) -> Sequence[Dict[str, Any]]:
        wanted = set(values)
        return [copy.deepcopy(e) for e in self._store.values() if e.get(column) in wanted]

    def delete_eq(self, column: str, value: Any) -> None:
        # Mirrors BaseRepo.delete_eq (and the sibling memory doubles
        # MemoryTransferLinksRepo / MemoryTxnEntityMapRepo). The export path
        # calls repos["entities"].delete_eq("deal_id", deal_id) before re-inserting
        # (api.py); without this the in-memory double diverges from the live repo.
        self._store = {k: v for k, v in self._store.items() if v.get(column) != value}


class MemoryTxnEntityMapRepo(TxnEntityMapRepository):
    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}

    def upsert_mappings(self, mappings: Iterable[Dict[str, Any]]) -> None:
        for m in mappings:
            self._store[m["txn_id"]] = copy.deepcopy(m)

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(m) for m in self._store.values() if m.get("deal_id") == deal_id]

    def list_needs_review_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [
            copy.deepcopy(m) for m in self._store.values()
            if m.get("deal_id") == deal_id and (m.get("role") or "").lower() == "needs_review"
        ]

    def update_role(self, txn_uuid: str, new_role: str) -> None:
        for m in self._store.values():
            if str(m.get("txn_id")) == str(txn_uuid):
                m["role"] = new_role

    def count_needs_review(self, deal_id: str) -> int:
        return len(self.list_needs_review_by_deal(deal_id))

    def get_by_deal_and_txn(self, deal_id: str, txn_id: str) -> Optional[Dict[str, Any]]:
        for m in self._store.values():
            if m.get("deal_id") == deal_id and str(m.get("txn_id")) == str(txn_id):
                return copy.deepcopy(m)
        return None

    def count_needs_review_excluding(self, deal_id: str, exclude_txn_id: str) -> int:
        return sum(
            1 for m in self._store.values()
            if m.get("deal_id") == deal_id
            and (m.get("role") or "").lower() == "needs_review"
            and str(m.get("txn_id")) != str(exclude_txn_id)
        )

    def delete_eq(self, column: str, value: Any) -> None:
        self._store = {k: v for k, v in self._store.items() if v.get(column) != value}


class MemoryOverridesRepo(OverridesRepository):
    def __init__(self):
        self._store: List[Dict[str, Any]] = []

    def insert_override(self, override: Dict[str, Any]) -> Dict[str, Any]:
        row = {**override, "created_at": override.get("created_at") or datetime.utcnow().isoformat()}
        self._store.append(row)
        return copy.deepcopy(row)

    def list_overrides(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(o) for o in self._store if o.get("deal_id") == deal_id]

    def get_latest_update_at(self, deal_id: str) -> Optional[str]:
        rows = [o for o in self._store if o.get("deal_id") == deal_id]
        if not rows:
            return ""
        return max((r.get("created_at") or "") for r in rows)


class MemoryOverrideLogRepo:
    """Mirrors OverrideLogRepo (pds_override_log) — append-only Review Queue
    resolution audit trail. Not part of the OverridesRepository interface;
    a separate table from pds_overrides (see PAR-77) — but PAR-111: still a
    real input to export()'s freshness check (get_latest_update_at below),
    since a resolution here changes what a re-export overlays onto
    run_pipeline()'s output."""

    def __init__(self):
        self._store: List[Dict[str, Any]] = []

    def insert_log(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        row = {**entry, "created_at": entry.get("created_at") or datetime.utcnow().isoformat()}
        self._store.append(row)
        return copy.deepcopy(row)

    def list_by_deal(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(o) for o in self._store if o.get("deal_id") == deal_id]

    def get_latest_update_at(self, deal_id: str) -> Optional[str]:
        rows = [o for o in self._store if o.get("deal_id") == deal_id]
        if not rows:
            return ""
        return max((r.get("created_at") or "") for r in rows)


class MemoryAnalysisRunsRepo(AnalysisRunsRepository):
    def __init__(self):
        self._store: List[Dict[str, Any]] = []

    def insert_run(self, run: Dict[str, Any]) -> Dict[str, Any]:
        row = {**run, "created_at": run.get("created_at") or datetime.utcnow().isoformat()}
        self._store.append(row)
        return copy.deepcopy(row)

    def list_runs(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [copy.deepcopy(r) for r in self._store if r.get("deal_id") == deal_id]

    def get_latest_run(self, deal_id: str) -> Optional[Dict[str, Any]]:
        rows = [r for r in self._store if r.get("deal_id") == deal_id]
        if not rows:
            return None
        latest = max(rows, key=lambda r: r.get("created_at") or "")
        return copy.deepcopy(latest)


class MemorySnapshotsRepo(SnapshotsRepository):
    def __init__(self):
        self._store: List[Dict[str, Any]] = []

    def insert_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        # Idempotent on sha256_hash to mirror DB unique constraint
        existing = self.get_by_hash(snapshot.get("sha256_hash"))
        if existing:
            return existing
        row = {**snapshot, "created_at": snapshot.get("created_at") or datetime.utcnow().isoformat()}
        self._store.append(row)
        return decode_snapshot_row(copy.deepcopy(row)) or copy.deepcopy(row)

    def get_by_hash(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        for s in self._store:
            if s.get("sha256_hash") == sha256_hash:
                return decode_snapshot_row(copy.deepcopy(s))
        return None

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        for s in self._store:
            if s["id"] == snapshot_id:
                return decode_snapshot_row(copy.deepcopy(s))
        return None

    def list_snapshots(self, deal_id: str) -> Sequence[Dict[str, Any]]:
        return [
            decode_snapshot_row(copy.deepcopy(s)) or copy.deepcopy(s)
            for s in self._store
            if s.get("deal_id") == deal_id
        ]

    def get_latest_snapshot(self, deal_id: str) -> Optional[Dict[str, Any]]:
        rows = [s for s in self._store if s.get("deal_id") == deal_id]
        if not rows:
            return None
        latest = max(rows, key=lambda r: r.get("created_at") or "")
        return decode_snapshot_row(copy.deepcopy(latest))


class MemoryExportPersistenceRepo:
    """Simulates export_persist_deal_state (migration 026, PAR-95) for tests.

    The real RPC gets its all-or-nothing behavior for free from Postgres
    wrapping one function call in one transaction. This double has no
    transaction to lean on, so it snapshots the four affected stores up
    front and restores them verbatim if anything raises partway through —
    otherwise a forced failure in a test would leave the in-memory stores
    empty (the exact bug PAR-95 fixes) instead of rolled back, and tests
    exercising the failure path would pass for the wrong reason.
    """

    def __init__(self, runs_repo, links_repo, entities_repo, txn_map_repo):
        self._runs = runs_repo
        self._links = links_repo
        self._entities = entities_repo
        self._txn_map = txn_map_repo

    def persist_deal_state(
        self,
        *,
        deal_id: str,
        run: Dict[str, Any],
        links: Iterable[Dict[str, Any]],
        entities: Iterable[Dict[str, Any]],
        txn_map: Iterable[Dict[str, Any]],
    ) -> None:
        runs_snapshot = copy.deepcopy(self._runs._store)
        links_snapshot = copy.deepcopy(self._links._store)
        entities_snapshot = copy.deepcopy(self._entities._store)
        txn_map_snapshot = copy.deepcopy(self._txn_map._store)
        try:
            self._txn_map.delete_eq("deal_id", deal_id)
            self._links.delete_eq("deal_id", deal_id)
            self._entities.delete_eq("deal_id", deal_id)
            self._runs.insert_run(run)
            self._links.insert_batch(links)
            self._entities.upsert_entities(entities)
            self._txn_map.upsert_mappings(txn_map)
        except Exception:
            self._runs._store = runs_snapshot
            self._links._store = links_snapshot
            self._entities._store = entities_snapshot
            self._txn_map._store = txn_map_snapshot
            raise


def build_memory_repos() -> Dict[str, Any]:
    runs = MemoryAnalysisRunsRepo()
    links = MemoryTransferLinksRepo()
    entities = MemoryEntitiesRepo()
    txn_map = MemoryTxnEntityMapRepo()
    return {
        "deals": MemoryDealsRepo(),
        "documents": MemoryDocumentsRepo(),
        "raw": MemoryRawTxRepo(),
        "links": links,
        "entities": entities,
        "txn_map": txn_map,
        "overrides": MemoryOverridesRepo(),
        "override_log": MemoryOverrideLogRepo(),
        "runs": runs,
        "snapshots": MemorySnapshotsRepo(),
        "export_persistence": MemoryExportPersistenceRepo(runs, links, entities, txn_map),
    }
