-- Migration 014: add currency_source to pds_deals
-- Replaces the "is the literal string KES" proxy that set_currency_if_unset() used
-- to decide whether a deal's currency was a creation-time placeholder or a real
-- detection. 'default' = placeholder from deal creation, 'detected' = confirmed by
-- a parsed document, 'manual' = reserved for a future explicit analyst override.
-- Backfill marks every deal that already has a currency as 'detected' so this
-- migration changes zero behavior for existing deals.
-- NOTE: migrator.py re-runs this file on every cold start. The backfill below is a
-- one-time data migration and must be coupled to column *creation*, otherwise it
-- re-stamps currency_source='detected' on every deploy and would clobber any future
-- 'manual' analyst override on a deal that has a currency. Guard on column existence.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'pds_deals'
      AND column_name = 'currency_source'
  ) THEN
    ALTER TABLE public.pds_deals
      ADD COLUMN currency_source TEXT NOT NULL DEFAULT 'default'
      CHECK (currency_source IN ('default', 'detected', 'manual'));

    -- One-time backfill: mark every pre-existing deal that already has a currency
    -- as 'detected' so this migration changes zero behavior for existing deals.
    UPDATE public.pds_deals SET currency_source = 'detected' WHERE currency IS NOT NULL;
  END IF;
END $$;
