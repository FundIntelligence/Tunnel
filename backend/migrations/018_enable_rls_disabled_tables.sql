-- Mirrors supabase/migrations/20260621073026_enable_rls_disabled_tables.sql
-- so the self-healing startup runner (backend/v1/db/migrator.py, which
-- re-runs every *.sql in this directory on every cold start against
-- DATABASE_URL) also re-asserts this. See that file for the full
-- investigation notes.
--
-- IF EXISTS guards: pds_musa_sessions does not exist on prod
-- (ifcdbhbuucmjgtjkluna) — without the guard this statement would error if
-- this runner's DATABASE_URL ever points at prod instead of staging. The
-- other four are no-ops on prod (RLS already enabled there).
ALTER TABLE IF EXISTS public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.deal_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.benchmark_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.pds_musa_sessions ENABLE ROW LEVEL SECURITY;
