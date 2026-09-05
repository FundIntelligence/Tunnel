# backend/migrations

Schema migrations for the `parity-staging` Supabase project (`kstuensfekanfberjubz`).

## How this works (since PAR-142)

Every file here gets applied to staging automatically by
[`.github/workflows/apply-backend-migrations.yml`](../../.github/workflows/apply-backend-migrations.yml)
on merge to `paritystaging`. The workflow tracks what it has already applied
in `public.backend_migrations_applied` (one row per filename), so it's safe
to re-run and only ever applies files it hasn't seen before.

**This is now the only path.** Before PAR-142, nothing applied this folder —
migrations reached staging by someone running them by hand (dashboard SQL
editor or a direct `psql` connection). That's how migration 027 ended up on
staging with no traceable origin. Don't go back to that.

### Adding a migration

1. Add a new file, numbered one higher than the current max (`ls backend/migrations`
   to check), e.g. `029_add_whatever.sql`. Numbers are zero-padded to 3 digits.
2. Write plain SQL. **Do not** add `IF NOT EXISTS` / `IF EXISTS` guards to make
   it "safe to re-run" — the CI tracking table already prevents re-application,
   and idempotency guards on top of that just hide a real second-application
   bug instead of failing loud.
3. Open a PR into `paritystaging` as normal. Once merged, the workflow applies
   it automatically. No manual step.

### What NOT to do

* **Don't** apply a migration by hand via the Supabase dashboard SQL editor or
  a direct `psql`/session-pooler connection, even "just this once." That's
  the exact gap PAR-142 closed — every hand-applied migration is untracked,
  unreviewable, and can race the CI path (this happened once already, see
  PAR-142's investigation write-up on the ticket).
* **Don't** edit an existing migration file after it's merged. Migrations are
  append-only — if something needs fixing, write a new migration.
* **Don't** hand-insert rows into `public.backend_migrations_applied`. The one
  exception is the one-time backfill for migrations 008-027 (already applied
  before this gate existed, confirmed present via schema inspection
  2026-08-13) — see the table comment in Supabase for that record. Every
  migration after that point should only ever get a tracking row from the CI
  workflow itself.

### Numbering gap

There is no `024_*.sql` file — that number was skipped historically, not a
deleted file. `025` follows `023` directly.

## Known gap, not closed by this workflow

This only gates *application*. Direct DDL access to staging (dashboard SQL
editor, raw `psql` with the session-pooler credentials) is still unrestricted
— PAR-142's original recommendation paired this workflow with restricting
that access, and explicitly said not to let the access-restriction half block
shipping this half. It's still open; someone can still bypass this workflow
by hand if they choose to. What this workflow does is remove the reason to.
