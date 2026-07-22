-- Migration 021: add storage_path to parser_requests (PAR-34).
--
-- Decision: parser_requests (automated/system-generated — Musa and GBFund
-- ingestion failures write here directly, e.g. musa_file_processor.py)
-- stays separate from pds_parser_requests (human-submitted — Amuriki's
-- manual parser-request form). Merging the two would recreate the same
-- two-things-one-table confusion PAR-45 just fixed one layer down (admin
-- queue reading the wrong table). Instead this closes parser_requests'
-- own file-persistence gap the same way 20260713000000 closed it for
-- pds_parser_requests: a storage_path column pointing at the sample file
-- in Storage, so a failed Musa/GBFund document isn't lost the moment the
-- signed URL it was downloaded from expires.
ALTER TABLE public.parser_requests
  ADD COLUMN IF NOT EXISTS storage_path text;
