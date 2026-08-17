-- Migration 030: document the rls_enabled_no_policy findings (PAR-143).
--
-- Supabase's security advisor flags 4 tables with RLS enabled and zero
-- policies: benchmark_metrics, parser_requests, pds_musa_sessions, profiles.
-- With RLS on and no policy, Postgres denies ALL access to anon/authenticated
-- by default -- only the service-role key (which bypasses RLS entirely)
-- can read or write. That is already the correct, locked-down state for
-- all 4 tables below; this migration adds no new policies, it records WHY
-- deny-all is the intended state rather than an oversight, so the next
-- person who sees this INFO-level finding doesn't have to re-derive it.
--
-- parser_requests and pds_musa_sessions: internal request/session logs
-- written only by backend/admin code using the service-role key, with no
-- per-user owner column to scope a policy to. Same reasoning migration 015
-- already applied to parser_requests explicitly (see that file) -- adding a
-- policy here would mean inventing an access pattern that doesn't exist in
-- the app. Deny-all-except-service-role is correct.
--
-- benchmark_metrics: zero references anywhere in backend/ or admin/ code
-- (confirmed via repo-wide grep, 2026-08-13) -- unused/not-yet-wired-up.
-- No policy to write because there's no real access pattern yet to write
-- one against. Deny-all is the safe default until this table is actually
-- used; revisit when it is.
--
-- profiles: also zero code references (confirmed via repo-wide grep,
-- 2026-08-13) despite the id/email/role shape suggesting an eventual
-- self-access pattern (auth.uid() = id). Not adding a self-access policy
-- now -- that would be guessing at intent for a table nothing reads or
-- writes yet, which is exactly what PAR-143 says not to do. Flagged, not
-- fixed: whoever wires this table up should add the real policy as part of
-- that work, informed by the actual access pattern being built, not this
-- migration's guess.
comment on table public.benchmark_metrics is
  'RLS enabled, no policy = deny-all except service_role, INTENTIONAL (PAR-143, 2026-08-13): table is unreferenced anywhere in backend/ or admin/ code. No access pattern exists to write a policy against. Revisit when this table is actually wired up.';

comment on table public.parser_requests is
  'RLS enabled, no policy = deny-all except service_role, INTENTIONAL (PAR-143/PAR-84/migration 015): internal request log, written only via service-role backend/admin code, no per-user owner column. Confirmed correct in PAR-84''s follow-up investigation.';

comment on table public.pds_musa_sessions is
  'RLS enabled, no policy = deny-all except service_role, INTENTIONAL (PAR-143, 2026-08-13): internal Musa integration session table, written only via service-role backend code (backend/v1/musa/), no per-user owner column.';

comment on table public.profiles is
  'RLS enabled, no policy = deny-all except service_role, FLAGGED NOT FIXED (PAR-143, 2026-08-13): table is unreferenced anywhere in backend/ or admin/ code today. Shape (id/email/role) suggests a future self-access policy (auth.uid() = id), but no policy was written here -- that would be guessing at an access pattern nothing currently implements. Add the real policy when this table is wired up, driven by that work''s actual requirements.';
