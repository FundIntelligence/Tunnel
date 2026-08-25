"""
PAR-192 — render entrypoint for the interim async PDF Cloud Run Job.

Invoked as a Cloud Run Job execution (see core/pdf_jobs.trigger_render_job),
NOT imported as a library and NOT run inline in the API service. This is
what actually gets full, unthrottled CPU for the ~90-105s render (see
core/pdf_jobs.py's module docstring for why that distinction matters).

Deliberately thin: does exactly one job, writes exactly one result, and
touches no rendering logic of its own. render_snapshot_html() and
_render_html_to_pdf() are reused completely unchanged -- this script's only
job is bookkeeping (mark_running / mark_done / mark_failed) around a call to
each. Same reasoning as regenerate_outputs.py's export_pdf(): do not
reimplement or approximate rendering here, ever.

USAGE (as invoked by the Cloud Run Job, via container args):
    python3 -m v1.scripts.render_pdf_job --job-id <uuid> --deal-id <uuid> --variant snapshot
"""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _render(deal_id: str, variant: str) -> bytes:
    """
    variant handling mirrors the three existing sync callers of
    _render_html_to_pdf in api.py (snapshot/pdf, snapshot/pdf/enriched,
    report) -- 'snapshot' is the only variant PAR-192 actually needs for
    Musa's reliability problem tonight; 'enriched' and 'report' are wired
    for completeness (this ticket's open question #3) but unexercised until
    a caller actually requests them.
    """
    # Lazy import: api.py constructs the full FastAPI router tree at module
    # load. Deferring this until the job is actually running keeps `--help`
    # and argument-parsing errors cheap, and matches regenerate_outputs.py's
    # existing pattern of importing generate_pdf lazily inside its function
    # rather than at module scope.
    from v1.api import _render_html_to_pdf
    from v1.analysis.snapshot_html_renderer import render_snapshot_html

    if variant not in ("snapshot", "enriched", "report"):
        raise ValueError(f"Unknown variant: {variant!r}")

    # All three existing sync endpoints call render_snapshot_html() with no
    # variant-specific arguments beyond deal_id -- enriched/report differ in
    # what the *caller* does with the bytes (filename, whether enrichment
    # data is fetched separately), not in how the HTML/PDF itself is built.
    # Preserved exactly as-is; not touched by PAR-192.
    html = render_snapshot_html(deal_id)
    return _render_html_to_pdf(html, deal_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--deal-id", required=True)
    parser.add_argument("--variant", required=True)
    args = parser.parse_args()

    from v1.core import pdf_jobs

    logger.info("[PAR-192] Starting render job_id=%s deal_id=%s variant=%s",
                args.job_id, args.deal_id, args.variant)
    pdf_jobs.mark_running(args.job_id)

    try:
        pdf_bytes = _render(args.deal_id, args.variant)
    except Exception as exc:  # noqa: BLE001 — report to the job row, don't crash silently
        logger.exception("[PAR-192] Render failed job_id=%s deal_id=%s", args.job_id, args.deal_id)
        pdf_jobs.mark_failed(args.job_id, repr(exc))
        return 1

    pdf_jobs.mark_done(args.job_id, pdf_bytes)
    logger.info("[PAR-192] Completed render job_id=%s deal_id=%s bytes=%d",
                args.job_id, args.deal_id, len(pdf_bytes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
