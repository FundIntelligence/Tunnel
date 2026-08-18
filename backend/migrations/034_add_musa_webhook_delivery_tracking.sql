-- Migration 034: webhook delivery tracking on musa_sessions (PAR-174)
--
-- Phase 1 of PAR-174 is an admin-triggered manual resend for a completed
-- Musa session's webhook. To let an admin see *why* the original delivery
-- failed before blindly retrying into the same failure mode, something has
-- to persist the outcome of each attempt — today musa_file_processor's
-- _send_webhook only logs it, so there is nothing an admin UI can read.
-- These columns are that persistence; _send_webhook writes them after every
-- attempt (original send or manual resend).
--
-- NOTE: numbered 034 instead of 033 to stay clear of PR #149 (PAR-178,
-- "allow 'admin' key_type on api_keys"), which claims 033 and was still
-- open/unmerged as of this migration's authorship. Unrelated tables, so
-- there is no ordering dependency between the two — this just avoids a
-- filename collision regardless of which merges first.

alter table public.musa_sessions
  add column webhook_last_status_code integer;

alter table public.musa_sessions
  add column webhook_last_attempted_at timestamptz;

alter table public.musa_sessions
  add column webhook_last_error text;

alter table public.musa_sessions
  add column webhook_delivered_at timestamptz;

alter table public.musa_sessions
  add column webhook_resend_count integer not null default 0;
