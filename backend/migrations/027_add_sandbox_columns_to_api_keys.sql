-- Migration 027: sandbox columns on api_keys (PAR-130)
--
-- api_keys today is Musa-shaped (partner_name, api_key_hash, active). Sandbox
-- keys — external, /v1/classify-only, capped at a fixed number of free calls —
-- are a different kind of row in the same table, not a second table.
--
-- key_type distinguishes the two: existing rows default to 'musa-partner' via
-- the column default, so no backfill statement is needed. status is separate
-- from key_type's revoke state so a key can be revoked without losing its
-- audit trail (no hard-delete on revoke).
--
-- calls_used/call_cap are schema-only in this migration — nothing calls
-- increment_api_key_usage() yet (POST /v1/classify doesn't exist). It's
-- included now, atomic by construction, so the future call site does not
-- reach for a delete-then-reinsert or read-then-write pattern — see PAR-93
-- for what that failure mode looks like in this codebase.
alter table public.api_keys
  add column key_type text not null default 'musa-partner',
  add column calls_used integer not null default 0,
  add column call_cap integer not null default 10000,
  add column status text not null default 'active';

alter table public.api_keys
  add constraint api_keys_key_type_check check (key_type in ('musa-partner', 'sandbox-classify')),
  add constraint api_keys_status_check check (status in ('active', 'revoked')),
  add constraint api_keys_calls_used_nonneg check (calls_used >= 0),
  add constraint api_keys_call_cap_positive check (call_cap > 0);

-- Atomic increment: single UPDATE ... RETURNING, so a concurrent caller
-- either lands inside the cap or gets no row back — never a lost update.
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
