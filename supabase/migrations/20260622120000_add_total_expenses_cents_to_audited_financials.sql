-- Mirror of backend/migrations/018_add_total_expenses_cents_to_audited_financials.sql
--
-- The income statement's OWN stated total-expenses line, transcribed verbatim by
-- the extractor (NOT a sum of the granular cost_of_sales / operating / admin /
-- staff / finance sub-categories). Authoritative reconciliation input for the
-- Expenses dimension; granular fields remain for gap-explanation narrative only.
-- Nullable: legacy-extractor and pre-existing rows leave it NULL, in which case
-- reconciliation falls back to summing the granular cost sub-categories.
alter table pds_audited_financials
  add column if not exists total_expenses_cents bigint null;

comment on column pds_audited_financials.total_expenses_cents is
  'Income statement total-expenses line as stated in the document (cents). '
  'Authoritative reconciliation input for expenses. NULL for rows predating this '
  'column or extracted by the legacy extractor; reconciliation then falls back to '
  'summing the granular cost sub-categories.';
