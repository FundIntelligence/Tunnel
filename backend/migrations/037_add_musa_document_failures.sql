-- Migration 037: per-document failure detail on musa_sessions (PAR-200)
--
-- PAR-200 found that process_musa_session's orchestrator loop discarded the
-- real, structured per-document failure reason (already correctly recorded
-- on each pds_documents row by process_document_background/_update_failed)
-- before it ever reached the session record. A session where 13 documents
-- failed for 3 distinct real reasons collapsed into one generic
-- musa_sessions.error_message with no way to tell which file failed why.
--
-- This column holds that detail: a JSON array of one object per failed
-- document (filename, error_type, error_message, next_action), written
-- alongside error_message rather than replacing it -- error_message stays
-- the short human summary, this is the itemised detail behind it. Nullable
-- with no default: a fully successful session, or a session created before
-- this migration existed, both correctly read as "no per-document failure
-- detail" rather than an empty array implying something was checked.

alter table public.musa_sessions
  add column document_failures jsonb;
