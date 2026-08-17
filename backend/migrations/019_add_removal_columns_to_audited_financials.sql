-- Soft-delete (removal) support for audited financials records.
--
-- An analyst who uploads a statement to the wrong deal, or uploads the wrong
-- file, needs to remove that financial-year record from the deal's queue without
-- hard-deleting it. This adds a soft-delete: the row is RETAINED for audit and
-- simply filtered out of every read by `removed_at IS NULL`.
--
--   removed_at     — when the record was removed (NULL = active / live)
--   removed_reason — analyst-supplied reason (required to supersede a CONFIRMED record)
--   removed_by     — Supabase user sub (or initials) of whoever removed it
--
-- Mirrors the existing 409 upload guard's tiering: unconfirmed records remove
-- freely; confirmed records are only removable via an explicit, attributed
-- supersede. A fresh upload for the same (deal, financial_year) re-activates the
-- row by clearing these columns back to NULL (see api.upload_audited_financials).
alter table pds_audited_financials
  add column if not exists removed_at     timestamptz null,
  add column if not exists removed_reason text        null,
  add column if not exists removed_by     text        null;

-- Active-record lookups (queue, 409 guard, confirm gate) all filter removed_at IS NULL.
create index if not exists idx_pds_af_active
  on pds_audited_financials(deal_id)
  where removed_at is null;

comment on column pds_audited_financials.removed_at is
  'Soft-delete marker. NULL = active. Set when an analyst removes the record from '
  'the deal queue; the row is retained for audit and filtered out of all reads. '
  'Cleared back to NULL when a fresh upload re-activates the same (deal, financial_year).';
comment on column pds_audited_financials.removed_reason is
  'Analyst-supplied reason for removal. Required when superseding a CONFIRMED record.';
comment on column pds_audited_financials.removed_by is
  'Supabase user sub (or initials) of whoever removed the record.';
