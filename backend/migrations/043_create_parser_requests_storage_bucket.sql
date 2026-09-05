-- PAR-248: Create the `parser-requests` Storage bucket that
-- musa_file_processor.py uploads raw documents to before parsing.
--
-- This bucket was created in staging (2026-07-13) but never provisioned in
-- prod. All parser_requests.storage_path values in prod have been NULL since
-- the Musa integration shipped because _persist_raw_document() silently
-- swallowed the "bucket not found" error on every call.
--
-- Confirmed 2026-09-04: prod Supabase project ifcdbhbuucmjgtjkluna has
-- exactly one bucket ("uploads"); this migration adds the second.
-- ON CONFLICT DO NOTHING makes the migration idempotent for staging, where
-- the bucket already exists.
--
-- 50 MB per-file cap: sufficient for bank statement PDFs/XLSX and large
-- enough to handle multi-statement batches; not so large as to allow
-- accidental full-financial-record dumps.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('parser-requests', 'parser-requests', false, 52428800, null)
ON CONFLICT (id) DO NOTHING;
