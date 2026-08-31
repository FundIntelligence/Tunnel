-- Migration 040: add pds_snapshots.computation_fingerprint (PAR-219)
--
-- Problem: export()'s cache short-circuit (backend/v1/api.py) decides whether
-- a sealed snapshot may be reused by comparing documents/overrides timestamps
-- and config_version. A backend code deploy is not in that set, so a shipped
-- computation-logic fix does NOT reach already-sealed deals. PAR-217 hit this
-- for real: a corrected reconciliation figure was live at 100% traffic while
-- every sealed deal kept serving the pre-fix number, with PR-merged /
-- build-SUCCESS / export-HTTP-200 all reporting healthy.
--
-- Why a new column rather than reusing config_version: config_version is part
-- of the canonical snapshot payload and therefore feeds sha256_hash and
-- financial_state_hash (core/snapshot_engine.py). Folding a source digest
-- into it would change every deal's sealed hash on any computation edit,
-- trip the golden-hash sentinel, and re-seal documents whose figures never
-- moved -- a deterministic-rules change, not a cache fix. This column is
-- written alongside the snapshot but is deliberately NOT part of any hashed
-- payload, so it can invalidate a stale cache while leaving every existing
-- hash byte-identical.
--
-- Nullable with no default and no backfill, on purpose: every pre-PAR-219 row
-- keeps NULL, and api.py treats NULL as "unknown provenance -> do not trust
-- the cache", which is exactly the desired behaviour for snapshots sealed
-- before this mechanism existed (including the PAR-217-affected ones). They
-- re-compute once on next export, then carry a real fingerprint from then on.
alter table pds_snapshots
  add column if not exists computation_fingerprint text;

comment on column pds_snapshots.computation_fingerprint is
  'PAR-219: short digest of the computation-logic source that produced this '
  'snapshot (see backend/v1/config.py COMPUTATION_FINGERPRINT). Compared by '
  'export()''s cache short-circuit so a computation deploy invalidates stale '
  'snapshots automatically. NULL means the snapshot predates this mechanism '
  'and must not be served from cache. Never part of sha256_hash or '
  'financial_state_hash.';
