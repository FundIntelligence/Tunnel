-- Migration 028: fix export_persist_deal_state NULL created_at (PAR-89 follow-up)
--
-- export_persist_deal_state (migration 026) inserts into pds_analysis_runs via
-- `select (jsonb_populate_record(null::pds_analysis_runs, p_run)).*`. The base
-- record for jsonb_populate_record is a typed NULL row (null::pds_analysis_runs),
-- not a row honoring column defaults — so any column absent from p_run (built
-- client-side in run_pipeline(), backend/v1/core/pipeline.py) is populated with
-- an explicit NULL. Because the INSERT then supplies NULL for that column
-- explicitly, Postgres does not fall back to the column default (`now()` for
-- created_at) the way a bare INSERT with the column omitted would. pipeline.py
-- never sets created_at on the analysis_run dict, so every export insert failed
-- with `null value in column "created_at" of relation "pds_analysis_runs"
-- violates not-null constraint` (23502). Confirmed live on parity-staging.
--
-- Fix: populate the record into a local variable and explicitly coalesce
-- created_at to now() before the insert, rather than relying on the table
-- default.
--
-- Second, unrelated bug in the same function surfaced once the above was
-- fixed: the pds_txn_entity_map insert extracts `role` from p_txn_map via
-- jsonb_to_recordset(...) as x(..., role text, ...), but pds_txn_entity_map.role
-- is role_enum, not text, so Postgres rejects the INSERT with "column \"role\"
-- is of type role_enum but expression is of type text" (42804). Cast it
-- explicitly. Everything else about the function is unchanged.
create or replace function export_persist_deal_state(
  p_deal_id uuid,
  p_run jsonb,
  p_links jsonb,
  p_entities jsonb,
  p_txn_map jsonb
) returns void
language plpgsql
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
