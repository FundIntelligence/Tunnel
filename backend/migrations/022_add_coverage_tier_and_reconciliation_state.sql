-- Migration 022: add coverage_tier and reconciliation_state to pds_analysis_runs
--
-- PAR-47: the existing `tier` column collapses two different signals into one
-- badge — coverage_bp (data completeness, real and computable today) and
-- reconciliation_status (structurally can never be OK yet, since no deal has
-- accrual data), so every deal with any data caps at Medium regardless of how
-- complete its coverage actually is. `tier`/`tier_capped`/`reconciliation_status`
-- keep their exact current meaning and values — every existing consumer
-- (musa_file_processor.py, api.py, the export page, pdf_generator.py,
-- snapshot_html_renderer.py, ask.py, the frontend TS contract) is unaffected.
--
-- These two new columns are an honest, additive split, computed from the same
-- underlying values as the old columns so they can never drift apart:
--   coverage_tier        — Low/Medium/High derived from final_confidence_bp
--                          ALONE, with no reconciliation-status gating.
--   reconciliation_state — replaces the collapsed "NOT_RUN" with five
--                          distinct, honest reasons (see CHECK constraint).
--
-- Plain text + CHECK (not a Postgres ENUM type) deliberately: adding a new
-- enum value later needs no migration, just a new set literal here. This
-- also sidesteps the exact failure mode already hit once with tier_enum /
-- reconciliation_status_enum (see api.py's "invalid input value for enum"
-- comment) — no risk of an unlisted new state hard-failing an INSERT/UPDATE
-- against a rigid CREATE TYPE ENUM.
--
-- Both columns are nullable: the 69 pre-existing pds_analysis_runs rows
-- (22 of them sealed into pds_snapshots) are NOT backfilled. They stay NULL
-- on those rows forever. Only runs computed from this migration forward
-- populate them, via the normal parse_complete pipeline.
alter table pds_analysis_runs
  add column if not exists coverage_tier text null,
  add column if not exists reconciliation_state text null;

alter table pds_analysis_runs
  add constraint pds_analysis_runs_coverage_tier_check
    check (coverage_tier is null or coverage_tier in ('Low', 'Medium', 'High'));

alter table pds_analysis_runs
  add constraint pds_analysis_runs_reconciliation_state_check
    check (
      reconciliation_state is null or reconciliation_state in (
        'OK',
        'FAILED_OVERLAP',
        'FAILED_ZERO_INFLOW',
        'PENDING_ACCRUAL_DATA',
        'NO_TRANSACTION_DATA'
      )
    );

comment on column pds_analysis_runs.coverage_tier is
  'Low/Medium/High derived from final_confidence_bp alone, independent of '
  'reconciliation_status. NULL on runs computed before this column existed '
  '(not backfilled). See tier for the legacy, reconciliation-capped signal.';

comment on column pds_analysis_runs.reconciliation_state is
  'Honest reconciliation reason: OK, FAILED_OVERLAP, FAILED_ZERO_INFLOW, '
  'PENDING_ACCRUAL_DATA (no accrual data supplied for this deal), or '
  'NO_TRANSACTION_DATA (no transactions yet). Replaces the collapsed '
  '"NOT_RUN" that reconciliation_status uses for three different situations. '
  'NULL on runs computed before this column existed (not backfilled).';
