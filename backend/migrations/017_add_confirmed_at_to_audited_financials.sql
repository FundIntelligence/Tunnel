-- Track explicit human confirmation of extracted audited/management financials.
-- NULL means the row was populated by extraction (or upload) and has not yet been
-- confirmed via "Save financial details" in the Confirm Extracted Details form.
-- The Documents-tab navigation gate blocks proceeding to Analysis while any FY
-- record for the deal has confirmed_at IS NULL.
-- IMPORTANT: this file is re-executed on EVERY backend cold start by
-- backend/v1/db/migrator.py (no applied-migration tracking — see its docstring).
-- The ADD COLUMN below is idempotent, but the legacy backfill is a ONE-TIME data
-- migration and must NOT re-run: an unguarded `update ... where confirmed_at is null`
-- re-stamps every genuinely-unconfirmed analyst record on every deploy, silently
-- defeating the confirm gate (PR #33). We therefore couple the backfill to column
-- *creation* via a guard that runs it only when the column does not yet exist.
do $$
begin
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'pds_audited_financials'
      and column_name = 'confirmed_at'
  ) then
    alter table pds_audited_financials
      add column confirmed_at timestamptz null;

    -- One-time backfill (runs only at first creation, and again only if a
    -- restore drops the column — at which point every surviving row is legacy):
    -- rows written before this column existed predate the confirmation gate
    -- entirely (several already drive sealed snapshots). Treat them as confirmed
    -- as of their last write rather than retroactively blocking analysed deals.
    update pds_audited_financials
    set confirmed_at = updated_at
    where confirmed_at is null;
  end if;
end $$;

comment on column pds_audited_financials.confirmed_at is
  'Set server-side when a human explicitly saves the Confirm Extracted Details form. '
  'NULL means extracted-but-unconfirmed. Reset to NULL whenever the record is '
  'overwritten by a fresh extraction upload for the same financial year.';
