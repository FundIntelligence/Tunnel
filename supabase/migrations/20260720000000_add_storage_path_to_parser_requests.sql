-- Mirrors backend/migrations/021_add_storage_path_to_parser_requests.sql
-- so the self-healing startup runner (backend/migrations/) also covers it.
--
-- Decision (PAR-34): parser_requests (automated/system-generated — Musa
-- and GBFund ingestion failures) stays separate from pds_parser_requests
-- (human-submitted — Amuriki's manual form). Merging them would recreate
-- the same two-things-one-table confusion PAR-45 fixed one layer down.
-- This closes parser_requests' own file-persistence gap the same way
-- 20260713000000 closed it for pds_parser_requests.
ALTER TABLE public.parser_requests
  ADD COLUMN IF NOT EXISTS storage_path text;
