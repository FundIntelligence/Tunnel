-- Add file-persistence + lifecycle columns to pds_parser_requests.
--
-- Purpose: parser-request sample files were previously never persisted — they
-- existed only as a base64 attachment on a Resend email. storage_path records
-- where the file now lives in the `parser-requests` Storage bucket; status +
-- processed_at give the request a lifecycle the admin queue and notifications
-- can track.
--
-- SCHEMA DRIFT NOTE: the live pds_parser_requests table (staging + prod) does
-- NOT match 015_pds_parser_requests.sql. The live table was altered out of band
-- and carries account_type / country / document_id / error_type /
-- original_filename and a TEXT deal_id — none of which are in 015 — and it had
-- no status column until this migration. These statements are written
-- idempotently (IF NOT EXISTS) so they apply cleanly to the live, drifted table.
-- Reconciling 015 with the real schema is tracked separately and intentionally
-- NOT done here.

alter table public.pds_parser_requests
  add column if not exists storage_path text,
  add column if not exists status text not null default 'new',
  add column if not exists processed_at timestamptz;
