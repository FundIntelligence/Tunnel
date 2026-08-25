-- Migration 035: pds_pdf_jobs table (PAR-192, interim async PDF pipeline)
--
-- Async render->store->serve for the existing synchronous WeasyPrint PDF
-- path, moving the ~90-105s render off the request/response cycle. This is
-- deliberately the narrow, interim shape PAR-192 scopes: no hash-based
-- staleness detection, no build_snapshot_context() dependency, expected to
-- be replaced by PAR-191's freshness-policy mechanism once that lands.
--
-- Storage choice: pdf_bytes lives IN the row (bytea), not in a new Storage
-- bucket. Reasoning (see docs/PAR-177-async-pdf-implementation-plan.md §3,
-- committed alongside this migration):
--   - Deed's real rendered PDF is 81,894 bytes -- comfortably inside a
--     Postgres row without TOAD pressure. No evidence yet that enriched/
--     report variants are materially larger.
--   - Prod's Supabase Storage currently has exactly one bucket ("uploads").
--     A "parser-requests" bucket is referenced by
--     backend/v1/integrations/musa_file_processor.py and
--     musa_parser_request_sla.py but does NOT exist in prod -- confirmed via
--     direct SQL against storage.buckets on project ifcdbhbuucmjgtjkluna
--     ("Parity", prod). That is a real, separate, pre-existing bug, flagged
--     on PAR-192 and not fixed here. Building this feature's first real use
--     of Storage on top of an already-broken bucket reference pattern is
--     exactly the risk this migration avoids by not needing a bucket at all.
--   - Bytes-in-row reuses the existing supabase-py table pattern with no new
--     infra, no new IAM, no new failure mode -- consistent with this being
--     an interim, tactical measure expected to be replaced by PAR-191.
--
-- This is a genuine divergence from PAR-192's literal "store in a cloud
-- storage bucket" scope line. Flagged explicitly on the PR and on PAR-192
-- for review -- not a unilateral reinterpretation to be discovered later.
--
-- RLS: no policy, same reasoning as migration 030 (pds_musa_sessions,
-- parser_requests, etc.) -- an internal job table written only by
-- service-role backend code (backend/v1/core/pdf_jobs.py), with access
-- control enforced at the application layer via the existing
-- _require_snapshot_access gate (api.py:406), not via a per-row owner
-- column. RLS enabled + zero policies = deny-all except service-role,
-- which is the correct state here, not an oversight.

create table public.pds_pdf_jobs (
  job_id            uuid primary key default gen_random_uuid(),
  deal_id           uuid not null references public.pds_deals(id),
  variant           text not null,       -- 'snapshot' | 'enriched' | 'report'
  status            text not null default 'pending',  -- pending | running | done | failed
  snapshot_id       uuid,                -- cache key: latest pds_snapshots.id at trigger time
  pdf_bytes         bytea,
  byte_size         integer,             -- populated on success, for observability without decoding bytea
  error_message     text,
  requested_by      text,                -- caller identity (api key partner_name or user id), for retrieval authorization
  created_at        timestamptz not null default now(),
  started_at        timestamptz,
  completed_at      timestamptz
);

comment on table public.pds_pdf_jobs is
  'RLS enabled, no policy = deny-all except service_role, INTENTIONAL (PAR-192, 2026-08-25): interim async PDF render job table, written only via service-role backend code (backend/v1/core/pdf_jobs.py). Access control is enforced at the application layer (_require_snapshot_access, api.py:406), not via a per-row owner column -- same pattern as migration 030''s pds_musa_sessions. Expected to be replaced by PAR-191''s freshness-policy mechanism; do not build further features on this table without checking PAR-191''s status first.';

alter table public.pds_pdf_jobs enable row level security;

create index pds_pdf_jobs_deal_id_idx on public.pds_pdf_jobs (deal_id);

-- Cache short-circuit lookup: "is there already a done job for this exact
-- (deal, variant, snapshot) combination" -- mirrors api.py:1039's existing
-- deterministic-cache idea (PAR-177 plan §1c).
create index pds_pdf_jobs_cache_lookup_idx
  on public.pds_pdf_jobs (deal_id, variant, snapshot_id, status);

-- Reaper query: "rows older than N days" for the retention sweeper
-- (~2 weeks per Uzo's suggestion, PAR-192 scope item 5).
create index pds_pdf_jobs_created_at_idx on public.pds_pdf_jobs (created_at);
