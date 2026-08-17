-- Migration 032: fix increment_api_key_usage()'s zero-row return shape (PAR-132)
--
-- Migration 027 declared this `returns public.api_keys` (a single composite
-- row, not setof) as a `language sql` function. When the internal
-- UPDATE...RETURNING matches zero rows (key revoked, or already at
-- call_cap), that declaration shape makes Postgres return one row of
-- all-NULLs instead of an empty result -- standard behavior for a
-- non-setof composite-returning SQL function, not a fluke.
--
-- parity-classify-sandbox (the first and, as of this migration, only real
-- caller of this function anywhere in the codebase) treats that all-NULL
-- row as a valid non-empty PostgREST response, so its 403 rejection path
-- for revoked/at-cap keys never fires -- confirmed live on PAR-132: a key
-- with call_cap=5 kept succeeding past 6, 7, 8+ calls with genuine
-- classification output. Only unknown-key 401s actually reject anything.
--
-- Nothing in backend/ calls this function yet (027's own comment: "nothing
-- calls increment_api_key_usage() yet"), so this isn't a live production
-- incident today -- but fixing it here, at the shared definition, means
-- whatever calls it next (Musa's real cap enforcement) doesn't inherit the
-- same hole.
--
-- Fix: declare `returns setof public.api_keys` instead of the bare
-- composite type. A setof-returning SQL function whose final query
-- produces zero rows returns a genuinely empty result set -- PostgREST
-- serializes that as `[]`, not `[{...all null...}]` -- which is exactly
-- the shape app/usage.py's `rows[0] if rows else None` already expects.
-- No caller code changes needed; only the function's return-type
-- declaration changes. Function body is otherwise identical to 027's.
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
