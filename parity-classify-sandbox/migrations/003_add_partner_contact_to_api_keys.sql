-- Migration 003: add partner_name / contact_email to sandbox api_keys (PAR-149)
--
-- Migration 001 deliberately dropped partner_name from this project's
-- api_keys table (no musa-partner traffic here, ever). PAR-149's admin UI
-- needs to issue and list keys per external sandbox partner, so both
-- columns come back here — nullable, since key creation has so far been
-- entirely manual/undocumented and any pre-existing rows won't have this
-- data. New rows issued through the admin UI always populate both.
alter table public.api_keys
  add column partner_name text,
  add column contact_email text;
