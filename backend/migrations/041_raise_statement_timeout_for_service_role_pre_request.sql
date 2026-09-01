-- Migration 041: raise statement_timeout for service_role requests via a
-- PostgREST db-pre-request hook (PAR-222).
--
-- Root cause, confirmed live against real prod (ifcdbhbuucmjgtjkluna)
-- 2026-09-01: PostgREST's actual Postgres login role is `authenticator`
-- (confirmed via pg_stat_activity.usename on the exact statement that gets
-- cancelled), not `service_role`. `authenticator` carries
-- `statement_timeout=8s` (`ALTER ROLE authenticator SET statement_timeout =
-- '8s'`, alongside `lock_timeout=8s`) at the session/login level. PostgREST's
-- role-switching for an authenticated service_role JWT uses `SET ROLE`,
-- which changes effective permissions but does NOT reset session-level GUCs
-- (like statement_timeout) that were set on the login role — so every
-- PostgREST-mediated call, including RPCs made with a service_role JWT,
-- still runs under authenticator's 8s ceiling. Previous investigation
-- (PAR-222's own comment thread, 2026-09-01 earlier) checked
-- pg_roles.rolconfig for `service_role` directly and found no override,
-- concluding calls inherit the DB's 2-minute default -- that was checking
-- the wrong role: PostgREST never logs in as service_role, it logs in as
-- authenticator and switches role after connecting.
--
-- export_persist_deal_state (migration 038's current, patched version) was
-- captured live via pg_stat_activity as the exact statement PostgreSQL
-- cancels with 57014 on large deals. Direct-call benchmarking of the same
-- RPC against a real 12,851-row deal (entities + txn_map upserts, deletes,
-- run insert -- everything the function does) completed in 3-8 seconds in
-- isolation with no contention -- i.e. the RPC's own SQL is not
-- algorithmically broken or unbatched-in-a-way-that-scales-badly, it is
-- simply a write big enough to sit right at (and, under real production
-- contention, over) an 8-second ceiling that exists to bound public
-- anon/authenticated API traffic, not trusted backend-only service_role
-- writes.
--
-- Fix: a `db-pre-request` hook (PostgREST's documented mechanism for this
-- exact class of problem) that raises statement_timeout to 90s -- roughly
-- 10x the ~3-8s measured cost for today's largest known deal (14,229 txns),
-- leaving real headroom -- but only for requests authenticated with a
-- service_role JWT. This backend's Supabase client is hard-coded to
-- SUPABASE_SERVICE_ROLE_KEY everywhere (one client factory, confirmed
-- previously for the RLS work on this same project) -- service_role is
-- never used by untrusted, publicly-reachable traffic. anon/authenticated
-- callers keep authenticator's existing 8s statement_timeout /
-- 8s lock_timeout untouched, so the deliberate DoS-protection ceiling on
-- public endpoints is not weakened.
--
-- Why this over batching the RPC itself: the RPC is not unbatched in the
-- way PAR-106 Bug 3's paginated reads were (that bug was N unindexed,
-- unordered pages producing duplicate rows -- a correctness issue as much
-- as a performance one). This RPC does a single set-based
-- INSERT...SELECT...ON CONFLICT per table, which Postgres already executes
-- efficiently as one operation; splitting it into multiple chunked
-- RPC calls would each be its own top-level statement (still subject to
-- statement_timeout independently) but would break the single-transaction
-- atomicity migration 026 introduced specifically to fix PAR-93/PAR-95's
-- non-atomic write race -- trading a correctness guarantee for a
-- performance fix aimed at a mischaracterized root cause. Raising the
-- timeout for the actual bottleneck (a policy ceiling, not a slow query)
-- keeps the atomic, single-statement design intact.
--
-- Why 90s and not raising it further or removing the cap entirely: matches
-- this codebase's existing convention of finite, generous-but-bounded
-- timeouts elsewhere (EXPORT_TIMEOUT_S=300 in the PAR-219 remediation
-- script's client-side HTTP timeout; Cloud Run's own --timeout=1200 on the
-- service). An unbounded service_role statement_timeout would remove
-- Postgres's own backstop against a genuinely runaway query -- 90s is a
-- deliberate, evidence-based number, not "as high as possible."
create or replace function public.pgrst_pre_request()
returns void
language plpgsql
as $$
begin
  if current_setting('request.jwt.claims', true)::jsonb->>'role' = 'service_role' then
    perform set_config('statement_timeout', '90000', true);
  end if;
end;
$$;

alter role authenticator set pgrst.db_pre_request = 'public.pgrst_pre_request';
