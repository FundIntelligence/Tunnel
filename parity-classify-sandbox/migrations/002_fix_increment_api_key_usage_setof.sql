-- Migration 002: fix increment_api_key_usage()'s zero-row return shape (PAR-132)
--
-- Same bug, same fix, as backend/migrations/032_fix_increment_api_key_usage_setof.sql
-- -- this project runs its own independent copy of the function against its
-- own database (vksrelnjoejzqkiwqano), not the shared one migration 027
-- defined on parity-staging. See 032's comment for the full root-cause
-- writeup; summary: `returns public.api_keys` (non-setof) made a zero-row
-- UPDATE...RETURNING come back as one row of all-NULLs instead of an empty
-- result, which app/usage.py's increment_usage_or_none() treated as a
-- valid non-empty row -- so main.py's 403 (revoked/at-cap) path never
-- fired. Confirmed live on PAR-132: a call_cap=5 key kept succeeding past
-- 6, 7, 8+ calls.
--
-- `returns setof public.api_keys` makes a zero-row match return a
-- genuinely empty result set, matching what the existing Python caller
-- already expects. No caller code changes needed.
create or replace function increment_api_key_usage(p_key_id uuid)
returns setof public.api_keys
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
