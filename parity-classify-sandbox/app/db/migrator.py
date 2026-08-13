"""
Startup migration runner for this service's own migrations/ directory.

Deliberately modeled on backend/v1/db/migrator.py's self-healing,
re-run-every-boot design (all *.sql files must be IF NOT EXISTS-guarded) —
that is the only migration-application mechanism this repo actually has
today. PAR-142 ("CI-apply-on-merge") is still Backlog / unbuilt as of this
writing; there is no CI step anywhere in .github/workflows that applies
backend/migrations/*.sql either, so "apply via the CI-apply discipline
PAR-142 established" is not yet a real path to route through. Using the
same boot-time mechanism backend/ already relies on is the closest
non-manual precedent available, and — critically — means this migration
is never hand-applied via dashboard/psql by a human or an agent session.

Uses SANDBOX_DATABASE_URL, not backend's DATABASE_URL — this service's
env vars are deliberately isolated from the main backend's (see
app/config.py), so a Cloud Run misconfiguration can't point this service's
migrator at parity-staging or vice versa.
"""
import logging
import pathlib
import os
import re

import psycopg2

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent.parent / "migrations"


def _get_conn():
    url = os.getenv("SANDBOX_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "SANDBOX_DATABASE_URL is not set. Add it to this service's Cloud Run "
            "env vars: ParitySandbox project -> Project Settings -> Database -> "
            "Connection string (URI)."
        )
    return psycopg2.connect(url)


def _migration_files() -> list:
    if not _MIGRATIONS_DIR.exists():
        logger.warning("[sandbox-migrator] migrations dir not found: %s", _MIGRATIONS_DIR)
        return []
    return sorted(f for f in _MIGRATIONS_DIR.glob("*.sql") if re.match(r"^\d+", f.name))


def run_pending_migrations() -> None:
    files = _migration_files()
    if not files:
        logger.info("[sandbox-migrator] no migration files found — skipping")
        return

    try:
        conn = _get_conn()
    except RuntimeError as e:
        logger.warning("[sandbox-migrator] %s — skipping migrations", e)
        return
    except Exception:
        logger.exception("[sandbox-migrator] failed to connect to SANDBOX_DATABASE_URL — skipping migrations")
        return

    applied, failed = 0, []
    try:
        for mf in files:
            sql = mf.read_text()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                applied += 1
            except Exception:
                conn.rollback()
                failed.append(mf.name)
                logger.exception("[sandbox-migrator] %s failed to apply", mf.name)
        logger.info(
            "[sandbox-migrator] re-asserted %d migration file(s), %d failed",
            applied, len(failed),
        )
        if failed:
            logger.error("[sandbox-migrator] failing migrations: %s", failed)
    finally:
        conn.close()
