-- Migration 031: enable RLS on backend_migrations_applied.
--
-- This table was created directly (not via a numbered migration, since it's
-- CI infrastructure metadata rather than product schema -- see the CI
-- workflow and backend/migrations/README.md) and its own creation was
-- missed by the same discipline it exists to enforce: Supabase's advisor
-- flagged it ERROR-level rls_disabled_in_public right after 029/030 applied.
-- Fixing it the same way as every other internal/service-role-only table
-- in this codebase (parser_requests, pds_musa_sessions): RLS on, zero
-- policies, so anon/authenticated get denied entirely and only the
-- service-role connection this CI workflow uses can read/write it.
alter table public.backend_migrations_applied enable row level security;

comment on table public.backend_migrations_applied is
  'Tracks backend/migrations/*.sql files applied to this database. Written to exclusively by .github/workflows/apply-backend-migrations.yml on merge to paritystaging (PAR-142). Rows for 008-027 are a one-time backfill: those files were already live on staging via an untracked raw-SQL path before this gate existed (see PAR-142 investigation), confirmed present via schema inspection on 2026-08-13. Do not hand-insert rows for new migrations going forward -- that defeats the point of the gate. RLS enabled with no policy (migration 031): deny-all except service_role, same pattern as parser_requests/pds_musa_sessions -- this table is only ever touched by the CI workflow''s service-role connection.';
