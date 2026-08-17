-- Migration 029: pin search_path on functions flagged by Supabase's
-- security advisor as function_search_path_mutable (PAR-143). A mutable
-- search_path lets a caller who can create objects in a schema earlier in
-- their own search_path shadow an unqualified name the function relies on
-- (e.g. a table or another function) -- privilege-escalation-adjacent, not
-- cosmetic. None of these 5 are SECURITY DEFINER, so the actual exposure is
-- lower than the worst case of this lint, but the standard fix is cheap and
-- correct regardless: pin search_path explicitly so name resolution can't
-- be influenced by the calling session's search_path.
alter function public.get_deal_batch_count(uuid) set search_path = public, pg_temp;
alter function public.pds_prevent_mutation() set search_path = public, pg_temp;
alter function public.update_pds_audited_financials_updated_at() set search_path = public, pg_temp;
alter function public.pds_snapshots_mutation_guard() set search_path = public, pg_temp;
alter function public.export_persist_deal_state(uuid, jsonb, jsonb, jsonb, jsonb) set search_path = public, pg_temp;
