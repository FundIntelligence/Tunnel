-- Migration 038: fix export_persist_deal_state — created_at NULL constraint
-- violation + role_enum cast (PAR-106 Bugs 1 & 2, previously diagnosed and
-- fixed in unmerged PR #118 but never landed on paritystaging).
--
-- Bug 1 (created_at): the RPC (migration 026) builds its pds_analysis_runs
-- insert via `jsonb_populate_record(null::pds_analysis_runs, p_run)`. The
-- base record for that call is a typed-NULL row, not one that honors column
-- defaults — so any column missing from the JSON payload comes out as an
-- explicit NULL, and Postgres does not fall back to the column's `now()`
-- default once a value (even NULL) is supplied. `pipeline.py`'s
-- analysis_run dict never sets created_at, so every export through this RPC
-- fails with `null value in column "created_at" ... violates not-null
-- constraint (23502)`. Reproduced live on paritystaging 2026-08-31 against
-- a fresh deal (a51050e5-538b-4bc8-9b0b-9c65e99459ad) — this is not
-- historical, it is presently blocking every export.
--
-- Bug 2 (role_enum cast): the same RPC's pds_txn_entity_map insert extracts
-- `role` via `jsonb_to_recordset(...) as x(..., role text, ...)`, but the
-- column is `role_enum`. Latent since migration 026 shipped, always masked
-- by Bug 1 firing first — fixing Bug 1 alone immediately surfaces this one
-- (`column "role" is of type role_enum but expression is of type text`,
-- 42804) on the very next export attempt.
--
-- Scope: only these two bugs. PAR-106's Bug 3 (non-deterministic pagination
-- duplicate-row upsert, BaseRepo.select_eq/select_eq2 missing .order()) is a
-- separate, unrelated code path (not this RPC) that only manifests on deals
-- with >1,000 raw transactions — out of scope here, still tracked on
-- PAR-106/open PR #118.
create or replace function export_persist_deal_state(
  p_deal_id uuid,
  p_run jsonb,
  p_links jsonb,
  p_entities jsonb,
  p_txn_map jsonb
) returns void
language plpgsql
set search_path = public, pg_temp
as $$
declare
  v_run pds_analysis_runs;
begin
  delete from pds_txn_entity_map where deal_id = p_deal_id;
  delete from pds_transfer_links where deal_id = p_deal_id;
  delete from pds_entities where deal_id = p_deal_id;

  v_run := jsonb_populate_record(null::pds_analysis_runs, p_run);
  v_run.created_at := coalesce(v_run.created_at, now());

  insert into pds_analysis_runs select v_run.*;

  insert into pds_transfer_links (deal_id, txn_out_id, txn_in_id, abs_amount_cents, match_rule_version)
  select deal_id, txn_out_id, txn_in_id, abs_amount_cents, match_rule_version
  from jsonb_to_recordset(p_links) as x(
    deal_id uuid, txn_out_id uuid, txn_in_id uuid,
    abs_amount_cents bigint, match_rule_version text
  );

  insert into pds_entities (entity_id, deal_id, normalized_name, display_name, strong_identifiers)
  select entity_id, deal_id, normalized_name, display_name, strong_identifiers
  from jsonb_to_recordset(p_entities) as x(
    entity_id text, deal_id uuid, normalized_name text,
    display_name text, strong_identifiers jsonb
  )
  on conflict (entity_id) do update set
    deal_id = excluded.deal_id,
    normalized_name = excluded.normalized_name,
    display_name = excluded.display_name,
    strong_identifiers = excluded.strong_identifiers;

  insert into pds_txn_entity_map (deal_id, txn_id, entity_id, role, role_version, role_reason)
  select deal_id, txn_id, entity_id, role::role_enum, role_version, role_reason
  from jsonb_to_recordset(p_txn_map) as x(
    deal_id uuid, txn_id uuid, entity_id text,
    role text, role_version text, role_reason text
  )
  on conflict (txn_id) do update set
    deal_id = excluded.deal_id,
    entity_id = excluded.entity_id,
    role = excluded.role,
    role_version = excluded.role_version,
    role_reason = excluded.role_reason;
end;
$$;
