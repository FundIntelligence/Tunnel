-- Migration 033: allow 'admin' as a key_type value on api_keys (PAR-175)
--
-- PAR-175 added an admin-panel-scoped x-api-key (api_keys.key_type = 'admin')
-- for the snapshot-pdf/html proxy route's auth path, but migration 027's
-- key_type CHECK constraint only permits 'musa-partner' and
-- 'sandbox-classify'. Any INSERT with key_type = 'admin' fails that CHECK
-- outright — this is what blocked backend/scripts/create_admin_api_key.py
-- from working against prod. Append-only per this folder's rules: drop the
-- old constraint, add a new one with 'admin' included, rather than editing
-- 027 in place.
alter table public.api_keys
  drop constraint api_keys_key_type_check;

alter table public.api_keys
  add constraint api_keys_key_type_check
    check (key_type in ('musa-partner', 'sandbox-classify', 'admin'));
