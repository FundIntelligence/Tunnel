-- Migration 023: add reason capture to pds_override_log (PAR-52)
--
-- Review Queue resolutions previously had no record of WHY a transaction was
-- reclassified — only original_role/override_role/analyst_initials. This adds
-- a reason to the existing append-only audit log; it does not touch
-- pds_txn_entity_map (which remains a materialized current-state cache,
-- rebuilt from the classifier on every export — see PAR-77 for the separate,
-- unrelated finding that overrides don't yet survive re-export).
--
-- Draft taxonomy (may be refined later, per product):
--   misclassified_rule_matching — classifier rule matched the wrong pattern
--   ambiguous_narrative         — bank narrative too sparse/unclear to classify confidently
--   known_exception             — analyst knows this client/deal has a standing exception
--   duplicate_reversal          — transaction is a duplicate or reversal, not a distinct event
--   other                       — anything else; reason_note required in this case
--
-- Both columns nullable: existing pds_override_log rows predate reason
-- capture and are not backfilled. The API requires reason_category on new
-- resolutions going forward; the DB does not enforce NOT NULL so old rows
-- remain valid as-is.
alter table pds_override_log
  add column if not exists reason_category text null,
  add column if not exists reason_note text null;

alter table pds_override_log
  add constraint pds_override_log_reason_category_check
    check (
      reason_category is null or reason_category in (
        'misclassified_rule_matching',
        'ambiguous_narrative',
        'known_exception',
        'duplicate_reversal',
        'other'
      )
    );

comment on column pds_override_log.reason_category is
  'Why the analyst reclassified this transaction. Draft taxonomy (PAR-52), '
  'may be refined later. NULL on rows resolved before this column existed.';

comment on column pds_override_log.reason_note is
  'Free-text elaboration. Required by the API when reason_category = ''other'', '
  'optional otherwise.';
