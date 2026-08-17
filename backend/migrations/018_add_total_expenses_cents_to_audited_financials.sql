-- Migration 018: add total_expenses_cents to pds_audited_financials
--
-- The income statement's OWN stated total-expenses line, transcribed verbatim by
-- the extractor (NOT a sum of the granular cost_of_sales / operating / admin /
-- staff / finance sub-categories). This is the authoritative reconciliation input
-- for the Expenses dimension; the granular fields remain populated for the
-- gap-explanation narrative only.
--
-- Nullable: rows written before this column existed, and any row produced by the
-- legacy pdfplumber extractor, do not populate it. Reconciliation falls back to
-- summing the granular cost sub-categories in that case, preserving prior behaviour.
--
-- Note: _PATCHABLE_AF_FIELDS in backend/v1/api.py and the AuditedFinancialsRecord
-- TS type already referenced this field; this migration makes the column exist.
alter table pds_audited_financials
  add column if not exists total_expenses_cents bigint null;

comment on column pds_audited_financials.total_expenses_cents is
  'Income statement total-expenses line as stated in the document (cents). '
  'Authoritative reconciliation input for expenses. NULL for rows predating this '
  'column or extracted by the legacy extractor; reconciliation then falls back to '
  'summing the granular cost sub-categories.';
