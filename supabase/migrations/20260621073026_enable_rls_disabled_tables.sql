-- Migration: enable RLS on 5 tables found with RLS fully disabled on
-- staging (kstuensfekanfberjubz) via a Supabase advisor scan. Different
-- table set from migrations 015/016 (parity_chat_sessions/parser_requests,
-- and the six dead pre-pds_ tables + uploads bucket).
--
-- Verified before applying: backend exclusively uses the service-role key
-- (backend/v1/db/supabase_client.py::get_supabase(), one client factory,
-- hard-coded to SUPABASE_SERVICE_ROLE_KEY) and service-role always bypasses
-- RLS, so this changes nothing for legitimate app traffic. Zero frontend/
-- admin/parity-ingestion code queries any of these 5 tables directly
-- (grepped for .from('profiles') etc. — no matches). No DB triggers
-- reference them. profiles/deals/deal_conversations/benchmark_metrics were
-- all empty or dev-test rows only (deals: 7 rows, all created_by the same
-- single test user_id, all status=draft, all within a 31-hour window).
--
-- deals/deal_conversations already had ownership-scoped policies sitting
-- inert (RLS was off) — enabling RLS here activates those, it doesn't
-- introduce new policy logic. profiles/benchmark_metrics/pds_musa_sessions
-- get no policies (default-deny), since nothing legitimately needs
-- anon/authenticated access to them.
--
-- This migration was originally applied directly via the Supabase MCP
-- (recorded in supabase_migrations.schema_migrations as version
-- 20260621073026 on staging) before being committed here — committing now
-- so the repo doesn't drift from the live schema the way migrations
-- 015/016 did (see v15 §6 item 4 and §5 Lessons Learned).
--
-- pds_musa_sessions does not exist on prod (ifcdbhbuucmjgtjkluna) — guarded
-- with IF EXISTS so this migration is safe to run against either project
-- without erroring. ENABLE ROW LEVEL SECURITY is itself idempotent (no
-- error if already enabled), which is also true for the other four
-- statements — prod already has RLS enabled on all four of those, this is
-- a no-op there.
ALTER TABLE IF EXISTS public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.deal_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.benchmark_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.pds_musa_sessions ENABLE ROW LEVEL SECURITY;
