-- Migration 026: export_persist_deal_state RPC (PAR-95)
--
-- backend/v1/api.py's export() persists a deal's run/links/entities/txn_map
-- as separate PostgREST calls — delete_eq("deal_id", deal_id) on txn_map,
-- links, entities, then insert_run/insert_batch/upsert_entities/upsert_mappings.
-- Each .table(x)...execute() auto-commits independently; there is no way to
-- span one Postgres transaction across them from supabase-py. Between the
-- deletes and the reinsert, pds_txn_entity_map (and links/entities) for the
-- deal sit genuinely EMPTY, and a concurrent resolve_transaction() call in
-- that window 404s. Confirmed live in production (PAR-93). PR #106 added a
-- critical-log safety net + client retry around this window as defense in
-- depth, but the window itself is still open.
--
-- This function moves the whole delete+reinsert sequence into a single
-- plpgsql function body. Postgres wraps one function call in one implicit
-- transaction, so if any statement inside fails — including a bad row in
-- the final insert — everything rolls back, including the deletes. Called
-- from export() via a single supabase-py .rpc() call, replacing the four
-- delete_eq calls and the four-call reinsert block.
--
-- Semantics match the current sequential calls exactly:
--   * pds_analysis_runs: plain insert (was insert_run) — id is generated
--     client-side in run_pipeline(), so no conflict target needed.
--   * pds_transfer_links: plain insert (was insert_batch) — no per-deal
--     conflict target; its unique constraints are on txn_in_id/txn_out_id
--     individually, both empty for this deal after the delete above.
--   * pds_entities: upsert on entity_id (was upsert_entities, PK entity_id).
--   * pds_txn_entity_map: upsert on txn_id (was upsert_mappings, PK txn_id).
--
-- Not SECURITY DEFINER — runs as the caller's role, same as
-- get_deal_batch_count and every other RPC in this project, so it is
-- subject to the same grants/RLS the caller already has via the direct
-- .table() calls it replaces.
create or replace function export_persist_deal_state(
  p_deal_id uuid,
  p_run jsonb,
  p_links jsonb,
  p_entities jsonb,
  p_txn_map jsonb
) returns void
language plpgsql
as $$
begin
  delete from pds_txn_entity_map where deal_id = p_deal_id;
  delete from pds_transfer_links where deal_id = p_deal_id;
  delete from pds_entities where deal_id = p_deal_id;

  insert into pds_analysis_runs
  select (jsonb_populate_record(null::pds_analysis_runs, p_run)).*;

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
  select deal_id, txn_id, entity_id, role, role_version, role_reason
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
