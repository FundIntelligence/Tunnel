-- Durable attribution for audited-financials confirmations.
--
-- The confirm gate (PR #33) asserts "a human approved this number" but, until now,
-- recorded no record of WHO confirmed or WHEN as a distinct event — which is why
-- prod mis-stamping from the 014/017 re-run bug could only be estimated, not proven.
-- This adds provable attribution going forward:
--   (1) pds_audited_financials.confirmed_by — Supabase user sub (JWT sub) of whoever
--       confirmed the record. NULL = confirmed before this column existed (legacy,
--       not retroactively attributed) OR a confirm that arrived without an
--       identifiable user (the handler now rejects those, so this should not occur
--       for new confirms).
--   (2) pds_af_confirm_log — append-only audit trail: one row per confirmation event.
--
-- ADDITIVE ONLY. There is NO data backfill / NO re-running UPDATE in this file
-- (see backend/v1/db/migrator.py: every file re-runs on each cold start; the 014/017
-- bug was an unguarded backfill). Every statement here is a no-op on re-run:
-- ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
-- DROP POLICY IF EXISTS + CREATE POLICY (the same idempotent policy pattern as 015/016).
-- Does NOT touch the snapshot/hash path; NO SCHEMA_VERSION bump.

-- (1) Attribution column on the AF record.
alter table pds_audited_financials
  add column if not exists confirmed_by text null;

comment on column pds_audited_financials.confirmed_by is
  'Supabase user sub (JWT sub) of whoever confirmed this record via the confirm '
  'handler. NULL = confirmed before this column existed (legacy, unattributed).';

-- (2) Append-only confirmation audit log.
create table if not exists pds_af_confirm_log (
  id              uuid primary key default gen_random_uuid(),
  deal_id         uuid not null references pds_deals(id) on delete cascade,
  financial_year  int  not null,
  confirmed_by    text null,
  confirmed_at    timestamptz not null default now(),
  source          text null,
  created_at      timestamptz not null default now()
);

create index if not exists idx_pds_af_confirm_log_deal
  on pds_af_confirm_log(deal_id, financial_year, created_at desc);

comment on table pds_af_confirm_log is
  'Append-only audit trail of audited-financials confirmation events. One row per '
  'confirm, recording who (confirmed_by), when (confirmed_at), and which FY/source.';

alter table pds_af_confirm_log enable row level security;

-- Owner-scoped, insert/select only (append-only: no update/delete policy).
-- Idempotent DROP+CREATE per the 015/016 pattern so the migrator can re-run safely.
drop policy if exists pds_af_confirm_log_select on pds_af_confirm_log;
create policy pds_af_confirm_log_select on pds_af_confirm_log
  for select using (
    exists (select 1 from pds_deals d
            where d.id = pds_af_confirm_log.deal_id and d.created_by = auth.uid())
  );

drop policy if exists pds_af_confirm_log_insert on pds_af_confirm_log;
create policy pds_af_confirm_log_insert on pds_af_confirm_log
  for insert with check (
    exists (select 1 from pds_deals d
            where d.id = deal_id and d.created_by = auth.uid())
  );
