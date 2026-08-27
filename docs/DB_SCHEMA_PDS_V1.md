# Parity v1 Database Schema (Deterministic / Immutable)

## Overview
- All money stored as integer cents (`*_cents BIGINT`); no floats anywhere.
- Snapshots are immutable (no UPDATE/DELETE) and store canonical JSON as TEXT to preserve ordering for hashing.
- RLS enforces per-deal ownership via `deals.created_by`.
- Basis points (`*_bp`) used for percentages to avoid floats.

## Enums
- `role_enum`: revenue_operational, revenue_non_operational, payroll, supplier, transfer, other
- `reconciliation_status_enum`: OK, NOT_RUN, FAILED_OVERLAP
- `tier_enum`: High, Medium, Low
- `document_status_enum`: uploaded, processing, completed, failed
- `analysis_state_enum`: LIVE_DRAFT
- `run_trigger_enum`: parse_complete, override_applied, manual_rerun

## Tables (high level)
- `deals`: owns currency (ISO 4217), accrual fields (`accrual_revenue_cents`, period start/end, manually_entered), owner `created_by`.
- `documents`: per-deal uploads; status enum; currency flags (`currency_detected`, `currency_mismatch`).
- `raw_transactions`: canonical rows, integer cents, non-zero enforced, deterministic `txn_id`; optional generated `abs_amount_cents`; FK to documents/deals; optional transfer link.
- `transfer_links`: one-to-one pairing (unique out/in), absolute amount, match rule version.
- `entities`: deterministic entity_id, normalized/display names, strong_identifiers JSONB; unique per deal.
- `txn_entity_map`: one entity per transaction, role enum, role_version.
- `overrides`: insert-only log; field (v1: role), weight 0.5/1.0; immutable by trigger + no update/delete RLS.
- `analysis_runs`: LIVE_DRAFT runs; integer cents totals; basis-point metrics; hashes for inputs.
- `snapshots`: immutable exports; unique sha256_hash; canonical_json TEXT; insert-only; idempotent by hash.

## RLS (summary)
- Enabled on all tables.
- Owner = `deals.created_by = auth.uid()`.
- Select/insert allowed for owner on all tables.
- Updates allowed only where needed: `deals`, `documents`; not allowed on `overrides`, `snapshots`, `raw_transactions`, `transfer_links`, `analysis_runs` (insert-only posture).
- Deletes not allowed for `overrides` and `snapshots`; generally avoided elsewhere (omit policies).

## Immutability
- Triggers `prevent_mutation` on `overrides` and `snapshots` raise on UPDATE/DELETE.
- Snapshots: unique `sha256_hash` ensures idempotent export; canonical_json TEXT preserves order for hashing (JSONB would reorder keys).

## Indexes (high value)
- `raw_transactions`: (deal_id, txn_date), (document_id), (deal_id, account_id, txn_date)
- `txn_entity_map`: (deal_id, role)
- `overrides`: (deal_id, entity_id, created_at desc)
- `analysis_runs`: (deal_id, created_at desc)
- `snapshots`: (deal_id, created_at desc), unique(sha256_hash)

## Notes
- Generated column `abs_amount_cents` used for convenience; if portability requires, compute in code instead of DB.
- Zero signed amounts are rejected (`signed_amount_cents <> 0`).
- Accrual fields live on `deals` with presence/order checks; used at reconciliation/export time.

## Schema Change Log (pilot)

The `pds_*` schema is frozen during pilot. Any `pds_*` migration promoted to
`main` must be recorded here in the same PR — this entry is the explicit,
auditable approval the CI schema-drift guard checks for.

Important: these are DB-only changes that do **not** affect the snapshot
financial-state payload, so `SCHEMA_VERSION` is intentionally **not** bumped
(`SCHEMA_VERSION` is hashed into every snapshot; bumping it would rewrite the
hash of all existing sealed snapshots). `SCHEMA_VERSION` is bumped only when the
snapshot/determinism engine changes.

| Date | Migration | Table | Change | Type |
|------|-----------|-------|--------|------|
| 2026-06-22 | `20260622000000_add_confirmed_at_to_audited_financials.sql` | `pds_audited_financials` | Add `confirmed_at timestamptz null` — explicit human confirmation of extracted financials; backfilled to `updated_at` for pre-existing rows. | Additive (nullable column) |
| 2026-06-22 | `20260622120000_add_total_expenses_cents_to_audited_financials.sql` | `pds_audited_financials` | Add `total_expenses_cents bigint null` — the income statement's stated total-expenses line; authoritative reconciliation input. | Additive (nullable column) |
| 2026-06-24 | `20260624000000_add_removal_columns_to_audited_financials.sql` (backend mirror `019_add_removal_columns_to_audited_financials.sql`) | `pds_audited_financials` | Add `removed_at timestamptz null`, `removed_reason text null`, `removed_by text null` — soft-delete so a wrongly-uploaded FY record can be removed from the deal queue (all reads filter `removed_at IS NULL`) and retained for audit. Confirmed records removable only via attributed supersede (`?supersede=true` + reason). Partial index `idx_pds_af_active`. | Additive (nullable columns) |
| 2026-06-24 | `20260624130000_add_confirmed_by_and_confirm_log.sql` (backend mirror `020_add_confirmed_by_and_confirm_log.sql`) | `pds_audited_financials`, **new** `pds_af_confirm_log` | Add `confirmed_by text null` (Supabase user sub of whoever confirmed). Add append-only `pds_af_confirm_log` (deal_id, financial_year, confirmed_by, confirmed_at, source) with owner-scoped insert/select RLS — durable per-event confirmation attribution. **No backfill / no re-running UPDATE** (idempotent re-run per migrator). | Additive (nullable column + new append-only table) |

All entries above are additive (nullable columns on `pds_audited_financials`,
plus the new append-only `pds_af_confirm_log` audit table) — analyst-uploaded
reference / attribution data, not part of the hashed snapshot state: no drops, no
type changes, no impact on `financial_state_hash` / `sha256_hash`.

| 2026-07-24 | `20260724070000_add_role_reason_to_txn_entity_map.sql` (backend mirror `025_add_role_reason_to_txn_entity_map.sql`) | `pds_txn_entity_map` | Add `role_reason text null` — PAR-89: human-readable reason a transaction was flagged `needs_review` (e.g. "KES 340,000 credit, no keyword match, 4.2x this business's median transaction size"), surfaced on the Review Queue. Additive (nullable column), no backfill. **Unlike the entries above, this DOES affect `financial_state_hash` going forward** — `txn_entity_map` (including this new field) is part of the hashed snapshot payload. Accompanied by `SCHEMA_VERSION` 1.0.2→1.0.3 and `CONFIG_VERSION` 1.0.3→1.0.4 in `backend/v1/config.py` in the same change (classifier.py's large-positive fallback logic also changed — see PAR-89), and a corresponding golden-hash-sentinel update. | Additive (nullable column) — hash-affecting, version-bumped |
| 2026-07-29 | `20260729000000_add_review_threshold_log.sql` (backend mirror `027_add_review_threshold_log.sql`) | **new** `pds_review_threshold_log` | PAR-89 part B: append-only diagnostics log, one row per transaction flagged via the large-positive-no-keyword-match fallback (`deal_id`, `txn_id`, `median_cents`, `mad_cents`, `threshold_cents`, `amount_cents`, `ratio`, `flagged_at`). `median_cents`/`mad_cents` are both null together when the flat KES 100,000 fallback fired instead of the relative statistic. Purpose: real false-positive/false-negative analysis once the review queue has usage data — join against `pds_override_log` on `deal_id` + `txn_id` at analysis time rather than parsing `role_reason` text. Deliberately write-once (no resolution-outcome columns; decision recorded in PAR-89 ticket comments). Best-effort write (try/except in `api.py`, modeled on `pds_intelligence_log`, not `pds_override_log` — a write failure never affects classification or export). Owner-scoped RLS enabled (unlike `pds_override_log`/`pds_intelligence_log`, flagged by PAR-84 as missing it). Does not affect `financial_state_hash` — never read by the pipeline or included in the snapshot payload; no version bump. | New table, RLS-enabled, non-hash-affecting |
