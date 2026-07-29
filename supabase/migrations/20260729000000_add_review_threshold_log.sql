-- Migration 027: pds_review_threshold_log (PAR-89 part B)
--
-- PAR-89's per-deal relative large-positive-credit threshold (median + scaled
-- MAD) is explicitly a heuristic, not a finalized design — see PAR-89's
-- "revisit when" criteria, item 1: "Real usage data exists — after analysts
-- have worked the review queue for a few weeks, use actual false-positive/
-- false-negative observations to tune the statistic/multiplier."
--
-- This table is that instrumentation: one append-only row per transaction
-- flagged via the large-positive-no-keyword-match fallback (not every
-- classification — just this specific heuristic), capturing the raw numbers
-- behind the decision (median/mad/threshold/ratio) so a later analysis query
-- can join against pds_override_log (deal_id + txn_id) to compute real
-- false-positive/negative rates, instead of parsing the human-readable
-- role_reason string.
--
-- Modeled on pds_intelligence_log, not pds_override_log: this is a
-- best-effort diagnostic record the pipeline never reads back (unlike
-- pds_override_log, which export() depends on to re-apply resolutions), so
-- the write is wrapped in try/except in application code and must never fail
-- classification or export. Deliberately write-once/append-only — no
-- resolution-outcome columns here; join against pds_override_log at analysis
-- time instead (decision recorded in PAR-89 ticket comments, 2026-07-29).
--
-- median_cents/mad_cents are both null together exactly when the flat
-- KES 100,000 fallback fired instead of the relative statistic (thin-data
-- deal, or degenerate MAD=0) — see compute_relative_large_positive_threshold_cents
-- in backend/v1/core/classifier.py.
CREATE TABLE IF NOT EXISTS pds_review_threshold_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id UUID NOT NULL REFERENCES pds_deals(id) ON DELETE CASCADE,
  txn_id UUID NOT NULL,
  median_cents BIGINT NULL,
  mad_cents BIGINT NULL,
  threshold_cents BIGINT NOT NULL,
  amount_cents BIGINT NOT NULL,
  ratio DOUBLE PRECISION NULL,
  flagged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_threshold_log_deal ON pds_review_threshold_log(deal_id);
CREATE INDEX IF NOT EXISTS idx_review_threshold_log_txn ON pds_review_threshold_log(txn_id);

-- RLS: deal-scoped, insert/select only (immutable log), matching the
-- pds_overrides/pds_analysis_runs pattern in supabase/migrations/003_pds_v1_prefixed.sql.
-- Deliberately NOT following pds_override_log/pds_intelligence_log, which
-- PAR-84 flags as missing RLS on 5 service-role tables — the backend's
-- service-role client bypasses RLS regardless, so this costs nothing and
-- avoids adding a 6th table to that exposure.
ALTER TABLE pds_review_threshold_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY pds_review_threshold_log_select ON pds_review_threshold_log
  FOR SELECT USING (EXISTS (SELECT 1 FROM pds_deals d WHERE d.id = pds_review_threshold_log.deal_id AND d.created_by = auth.uid()));
CREATE POLICY pds_review_threshold_log_insert ON pds_review_threshold_log
  FOR INSERT WITH CHECK (EXISTS (SELECT 1 FROM pds_deals d WHERE d.id = pds_review_threshold_log.deal_id AND d.created_by = auth.uid()));
