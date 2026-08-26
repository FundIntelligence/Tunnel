-- Migration 036: preserve the ORIGINAL webhook delivery time on musa_sessions
-- (PAR-174 follow-up)
--
-- Migration 034 added webhook_delivered_at, which _send_webhook overwrites on
-- every successful attempt. That is deliberate and stays as-is: it answers
-- "when did Musa last successfully receive this?", which is what the admin UI
-- needs after a resend. The cost is that the FIRST successful delivery time is
-- destroyed by the first resend — surfaced concretely during PAR-174's
-- 2026-08-26 re-verification, where resending session 2847fbf0 overwrote its
-- real 2026-08-18 delivery timestamp with no way to recover it.
--
-- This column is that missing audit fact. _send_webhook stamps it on the first
-- successful delivery only and never touches it again, so the two columns
-- answer two different questions: first_delivered_at = "when did this session's
-- result first reach Musa", delivered_at = "when did it most recently reach
-- Musa". Nullable with no default: rows that have never been delivered, and
-- rows delivered before this migration existed, both correctly read as unknown
-- rather than being backfilled with a timestamp nobody can vouch for.

alter table public.musa_sessions
  add column webhook_first_delivered_at timestamptz;
