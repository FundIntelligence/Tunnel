#!/usr/bin/env python3
"""PAR-219 remediation: force-refresh snapshots sealed by pre-fix code.

Why this exists
---------------
export()'s cache short-circuit never treated a backend code deploy as an
invalidation signal, so a shipped computation-logic fix did not reach deals
that already had a sealed snapshot. PAR-217 is the concrete case: a corrected
reconciliation figure went live at 100% traffic while every sealed deal kept
serving the pre-fix number.

The code fix (migration 040 + config.COMPUTATION_FINGERPRINT + the
short-circuit check) makes *future* deploys self-invalidating. It does not by
itself repair deals already sealed with wrong figures, because those rows are
only re-computed the next time someone happens to call export() for them.
This script does that pass deliberately rather than waiting for organic
traffic.

What it does
------------
For each deal, calls POST /v1/deals/{id}/export?force=true, which bypasses the
short-circuit entirely and re-seals from current logic. force=true is the
correct tool *here* — a one-off, auditable remediation sweep — as opposed to
being the standing workaround for the caching bug itself, which is what
PAR-219 was filed to eliminate.

Safety
------
- Dry-run by default. Nothing is called without --execute.
- --limit N to rehearse against a small batch first (recommended).
- Sequential with a pause between deals: export is a heavy call (observed
  ~50-90s on a 12.8k-transaction deal) and this must not stampede the service.
- Per-deal failures are recorded and reported, never abort the run: one bad
  deal must not strand the rest half-remediated.
- Re-runnable. A deal already carrying the current fingerprint is cheap to
  re-seal and produces an identical hash, so a partial run can simply be
  repeated.

Usage
-----
    # See what would happen (default):
    python backend/scripts/par219_force_restale_snapshots.py --created-by <uuid>

    # Rehearse against 2 deals for real:
    python backend/scripts/par219_force_restale_snapshots.py \
        --created-by <uuid> --limit 2 --execute

    # Full sweep:
    python backend/scripts/par219_force_restale_snapshots.py \
        --created-by <uuid> --execute
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://parity-backend-121148713552.us-central1.run.app"
ORIGIN = "https://parity-sme-staging.vercel.app"
EXPORT_TIMEOUT_S = 300
PAUSE_BETWEEN_DEALS_S = 3


def _get(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={"Origin": ORIGIN})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, timeout: int = EXPORT_TIMEOUT_S) -> dict:
    req = urllib.request.Request(url, method="POST", headers={"Origin": ORIGIN})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_deals(base: str, created_by: str) -> list[dict]:
    data = _get(f"{base}/v1/deals?created_by={created_by}")
    return data.get("deals", [])


def latest_snapshot_meta(base: str, deal_id: str) -> dict | None:
    """Read the deal's snapshot metadata without forcing a recompute."""
    try:
        data = _get(f"{base}/v1/deals/{deal_id}/snapshots")
    except urllib.error.HTTPError:
        return None
    snaps = data.get("snapshots") or []
    return snaps[0] if snaps else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE, help="backend base URL")
    ap.add_argument("--created-by", required=True, help="user id whose deals to sweep")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N deals")
    ap.add_argument("--execute", action="store_true", help="actually call export (default: dry run)")
    ap.add_argument(
        "--deal-id",
        action="append",
        default=None,
        help="restrict to specific deal id(s); repeatable",
    )
    args = ap.parse_args()

    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"PAR-219 remediation — {mode}")
    print(f"base={args.base}")

    if args.deal_id:
        deals = [{"id": d, "name": "(explicit)"} for d in args.deal_id]
    else:
        deals = list_deals(args.base, args.created_by)
    if args.limit is not None:
        deals = deals[: args.limit]

    print(f"deals in scope: {len(deals)}\n")

    refreshed: list[tuple[str, str, str]] = []
    unchanged: list[str] = []
    failed: list[tuple[str, str]] = []

    for i, deal in enumerate(deals, 1):
        deal_id = deal["id"]
        label = deal.get("name") or ""
        before = latest_snapshot_meta(args.base, deal_id)
        before_hash = (before or {}).get("sha256_hash")
        before_fp = (before or {}).get("computation_fingerprint")

        if before is None:
            print(f"[{i}/{len(deals)}] {deal_id} {label} — no snapshot, skipping")
            continue

        print(f"[{i}/{len(deals)}] {deal_id} {label}")
        print(f"    before: hash={str(before_hash)[:12]}… fingerprint={before_fp}")

        if not args.execute:
            print("    would POST export?force=true (dry run)\n")
            continue

        try:
            t0 = time.time()
            res = _post(f"{args.base}/v1/deals/{deal_id}/export?force=true")
            elapsed = time.time() - t0
            after_hash = (res.get("snapshot") or {}).get("sha256_hash")
            if after_hash and after_hash != before_hash:
                print(f"    after : hash={str(after_hash)[:12]}… CHANGED in {elapsed:.0f}s\n")
                refreshed.append((deal_id, str(before_hash), str(after_hash)))
            else:
                print(f"    after : hash unchanged ({elapsed:.0f}s) — figures already current\n")
                unchanged.append(deal_id)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            print(f"    FAILED HTTP {exc.code}: {body}\n")
            failed.append((deal_id, f"HTTP {exc.code}: {body}"))
        except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
            print(f"    FAILED: {exc!r}\n")
            failed.append((deal_id, repr(exc)))

        time.sleep(PAUSE_BETWEEN_DEALS_S)

    print("=" * 60)
    print(f"refreshed (hash changed): {len(refreshed)}")
    print(f"unchanged (already correct): {len(unchanged)}")
    print(f"failed: {len(failed)}")
    for deal_id, before_hash, after_hash in refreshed:
        print(f"  CHANGED {deal_id}: {before_hash[:12]}… -> {after_hash[:12]}…")
    for deal_id, err in failed:
        print(f"  FAILED  {deal_id}: {err}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
