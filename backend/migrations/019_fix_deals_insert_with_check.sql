-- Mirrors supabase/migrations/20260621075014_fix_deals_insert_with_check.sql
-- so the self-healing startup runner also re-asserts this. See that file
-- for the full investigation notes. Confirmed prod (ifcdbhbuucmjgtjkluna)
-- already has this exact WITH CHECK clause — this statement is a no-op
-- there, staging-only drift is what it actually fixes.
ALTER POLICY "Users can insert their own deals" ON public.deals
  WITH CHECK ((created_by)::text = (auth.uid())::text);
