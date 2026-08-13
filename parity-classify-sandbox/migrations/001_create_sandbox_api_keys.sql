-- Migration 001: sandbox api_keys table on the isolated ParitySandbox
-- project (vksrelnjoejzqkiwqano) — PAR-132 follow-up.
--
-- This is a fresh table on a dedicated, isolated project, not a copy of
-- parity-staging's musa+sandbox shared api_keys table (backend/migrations/027).
-- Every row here is sandbox-classify traffic only, so key_type/status/
-- calls_used/call_cap are mirrored from migration 027 (same columns, same
-- semantics, same increment_api_key_usage() guard) but partner_name is
-- dropped — there is no musa-partner traffic on this project, ever.
--
-- `active` is kept even though every row defaults true and this table has
-- no second key_type to distinguish: backend/v1/integrations/auth.py's
-- require_scoped_api_key / validate_scoped_api_key are reused UNMODIFIED
-- against this table (PAR-131, don't rebuild), and that shared query
-- filters on `.eq("active", True)` — dropping the column would break that
-- reuse, not simplify it.
--
-- RLS is enabled in the same migration that creates the table — not a
-- follow-up — per PAR-84 (RLS disabled on api_keys was independently
-- flagged on both kstuensfekanfberjubz and the prior kmgggdrpfsxtvyhjqncy
-- project by Supabase's own advisories). No policies are created: this
-- table is service-role-only by design (SANDBOX_SUPABASE_SERVICE_ROLE_KEY
-- bypasses RLS, as service_role always does). RLS enabled + zero policies
-- means anon/authenticated get zero rows and zero writes, which is the
-- correct default until/unless a non-service-role caller ever needs direct
-- access.
create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(),
  api_key_hash text not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  key_type text not null default 'sandbox-classify',
  calls_used integer not null default 0,
  call_cap integer not null default 10000,
  status text not null default 'active',
  constraint api_keys_key_type_check check (key_type in ('sandbox-classify')),
  constraint api_keys_status_check check (status in ('active', 'revoked')),
  constraint api_keys_calls_used_nonneg check (calls_used >= 0),
  constraint api_keys_call_cap_positive check (call_cap > 0)
);

alter table public.api_keys enable row level security;

-- Atomic increment, identical guard to migration 027's version: a single
-- UPDATE ... RETURNING, so a concurrent caller either lands inside the cap
-- or gets no row back — never a lost update. A NULL/empty return means
-- revoked (status != 'active') or at-cap (calls_used >= call_cap) — the two
-- are indistinguishable at this layer by design; the caller (parity-classify-
-- sandbox's app/usage.py) treats both as a hard rejection.
create or replace function increment_api_key_usage(p_key_id uuid)
returns public.api_keys
language sql
set search_path = public
as $$
  update public.api_keys
  set calls_used = calls_used + 1
  where id = p_key_id
    and status = 'active'
    and calls_used < call_cap
  returning *;
$$;
