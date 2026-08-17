-- Track explicit human confirmation of extracted audited/management financials.
-- NULL means the row was populated by extraction (or upload) and has not yet been
-- confirmed via "Save financial details" in the Confirm Extracted Details form.
-- The Documents-tab navigation gate blocks proceeding to Analysis while any FY
-- record for the deal has confirmed_at IS NULL.
alter table pds_audited_financials
  add column if not exists confirmed_at timestamptz null;

comment on column pds_audited_financials.confirmed_at is
  'Set server-side when a human explicitly saves the Confirm Extracted Details form. '
  'NULL means extracted-but-unconfirmed. Reset to NULL whenever the record is '
  'overwritten by a fresh extraction upload for the same financial year.';

-- Backfill: rows written before this column existed predate the confirmation gate
-- entirely (several already drive sealed snapshots). Treat them as confirmed as of
-- their last write rather than retroactively blocking already-analysed deals.
update pds_audited_financials
set confirmed_at = updated_at
where confirmed_at is null;
