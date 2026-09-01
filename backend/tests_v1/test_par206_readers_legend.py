"""
PAR-206 — reader's legend ("How to read this report") as Act 1's second element.

The legend is STATIC template content: it explains the report's own vocabulary
and running order, and reads no computed field. That property is the point of
the ticket — a legend that varies with the deal can go stale against it — so
most of this suite exists to pin "static" as a testable invariant rather than
an intention, by rendering the real Jinja template through two deliberately
divergent contexts and asserting the legend block comes out byte-identical.

Render harness: `_minimal_render_ctx` / `_real_recon_rows` are imported from
test_par116_four_act_structure rather than re-typed here, deliberately. Both
suites assert against the same production render contract, and a private copy
would let this file keep passing against a context shape the template had
already moved away from. If PAR-116's harness changes, this suite should be
made to face that change, not insulated from it.

Every definition asserted below was re-verified against the code on 2026-08-31
(post-outage re-check, base origin/paritystaging @ 03d8542):

  tiers        snapshot_generator._compute_tier() + _TIER_HIGH_STATUSES /
               _TIER_MEDIUM_STATUSES (snapshot_generator.py:25-26, 92-120).
               HIGH requires cash AND loan both EXACT_MATCH; a CRITICAL
               coverage advisory (>15% of declared cash unsubmitted) demotes an
               otherwise-HIGH deal to MEDIUM. MINOR/MATERIAL/NEGLIGIBLE do not.
  OBSERVED     the recon_available=False path — no audited financials submitted
               (snapshot_html_renderer.py:880, "Observed · bank data only").
  status tags  snapshot_context._resolve_recon_status() (:1298-1309), whose
               COVERAGE_GAP-vs-VARIANCE split is driven purely by
               coverage_incomplete — the distinction the legend must teach.
  tolerances   reconciliation_engine._EXACT_MATCH_CENTS = 1_000 (KES 10) and
               _ACCEPTABLE_BP = 500 (5%) (:50-53).
  needs_review core/classifier.classify_with_reason() (:462), including the
               `direction_conflict:*` branch (:529-531) the legend paraphrases
               as "the match contradicted the direction of the amount".

Deliberately NOT asserted: any citation to an external specification document.
A reader holding this report cannot open one, so naming it would resolve to
nothing for them; where the fuller specification lives is recorded on the
ticket instead.
"""
import os
import re
import sys

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from jinja2 import Environment, FileSystemLoader

from backend.tests_v1.test_par116_four_act_structure import (
    _minimal_render_ctx,
    _real_recon_rows,
    _EXPECTED_HEADINGS_BOTH_STATES,
    _EXPECTED_HEADINGS_RECON_AVAILABLE,
    _EXPECTED_HEADINGS_RECON_UNAVAILABLE,
)

_TEMPLATES_DIR = os.path.join(_BACKEND, "v1", "templates")

_LEGEND_HEADING = "How to read this report"


@pytest.fixture(scope="module")
def _template():
    env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR))
    return env.get_template("snapshot.html")


def _render(_template, recon_available: bool, **overrides) -> str:
    if recon_available:
        recon_ctx = _real_recon_rows()
        ctx = _minimal_render_ctx(
            True,
            recon_rows=recon_ctx["recon_rows"],
            recon_fiscal_note=recon_ctx["recon_fiscal_note"],
        )
    else:
        ctx = _minimal_render_ctx(False)
    ctx.update(overrides)
    return _template.render(**ctx)


def _legend_block(html: str) -> str:
    """The rendered legend, from its .sec-label through the closing .legend-foot."""
    start = html.index(_LEGEND_HEADING)
    end = html.index("</div>", html.index('class="legend-foot"', start))
    return html[start:end]


def _visible_text(block: str) -> str:
    """
    Lowercased prose with the markup removed.

    Scanning raw HTML for verdict words gives false positives off the class
    names themselves — "bad" lives inside `sec-label-badge`. The boundary this
    suite enforces is about what a READER sees, so strip tags first and match on
    word boundaries.
    """
    return re.sub(r"<[^>]+>", " ", block).lower()


# ── placement: Act 1's second element ───────────────────────────────────────

@pytest.mark.parametrize("recon_available", [True, False])
def test_legend_is_second_element_of_act_one(_template, recon_available):
    """
    Orientation before evidence: Key Metrics establishes what the deal is, the
    legend then explains how to read everything after it. It must sit inside
    Act 1 and ahead of Data Submitted / Account Coverage, in BOTH recon states
    — the observed-only report needs the vocabulary at least as much.
    """
    html = _render(_template, recon_available)
    i_act1 = html.index("Act 1 — Orientation")
    i_metrics = html.index("Key Metrics")
    i_legend = html.index(_LEGEND_HEADING)
    i_submitted = html.index(">Data Submitted<")
    i_act2 = html.index("Act 2 — Core Reconciliation")
    assert i_act1 < i_metrics < i_legend < i_submitted < i_act2


@pytest.mark.parametrize("recon_available", [True, False])
def test_legend_renders_exactly_once(_template, recon_available):
    html = _render(_template, recon_available)
    assert html.count(_LEGEND_HEADING) == 1
    assert html.count('class="legend-intro"') == 1
    assert html.count('class="legend-foot"') == 1


# ── the static invariant ────────────────────────────────────────────────────

def test_legend_is_byte_identical_across_both_recon_states(_template):
    """The whole point of the ticket: the legend cannot go stale against a deal
    because it never reads one."""
    assert _legend_block(_render(_template, True)) == _legend_block(
        _render(_template, False)
    )


def test_legend_is_byte_identical_under_wholly_different_deal_data(_template):
    """
    Stronger than the recon-state check: perturb every context value the legend
    could plausibly reach for — company, tier, currency, coverage, counts — and
    require the block not to move by a single byte.
    """
    base = _render(_template, True)
    perturbed = _render(
        _template, True,
        company_name="Some Other Company Plc",
        currency="USD",
        recon_tier="HIGH_CONFIDENCE",
        tier_badge_text="High confidence",
        tier_badge_class="tier-high",
        total_txn_count=1,
        period_label="Jan-Dec 2019",
        account_coverage={
            "available": True, "advisory_tier": "NEGLIGIBLE", "coverage_pct": 100.0,
            "submitted_count": 9, "declared_count": 9, "missing_balance_str": "KES 0",
            "coverage_color_class": "ok", "accounts": [], "recommendation": "", "note": "",
        },
    )
    assert _legend_block(base) == _legend_block(perturbed)


def test_legend_markup_contains_no_jinja_substitution(_template):
    """
    A guard with teeth against future edits: the legend's source must have no
    {{ }} / {% %} in it at all. Rendering-equality tests above would still pass
    if someone interpolated a value that happened to be constant across the
    contexts tried here; this pins the source itself.
    """
    src = open(os.path.join(_TEMPLATES_DIR, "snapshot.html"), encoding="utf-8").read()
    start = src.index("<div class=\"legend\">")
    end = src.index("</div>", src.index('class="legend-foot"', start))
    block = src[start:end]
    assert "{{" not in block and "{%" not in block


# ── definitions match what the code actually computes ───────────────────────

@pytest.mark.parametrize("tier", [
    "HIGH_CONFIDENCE", "MEDIUM_CONFIDENCE", "LOW_CONFIDENCE", "OBSERVED",
])
def test_legend_defines_every_tier_the_system_can_emit(_template, tier):
    assert tier in _legend_block(_render(_template, True))


def test_legend_states_the_real_tolerances(_template):
    """KES 10 and 5% are the actual _EXACT_MATCH_CENTS / _ACCEPTABLE_BP values —
    not rounded, not 'a small amount'."""
    block = _legend_block(_render(_template, True))
    assert "KES 10" in block
    assert "5%" in block


def test_legend_distinguishes_coverage_gap_from_variance(_template):
    """
    The single most load-bearing distinction in the report, and the one a reader
    is most likely to get wrong: both mean "the numbers differ", but a GAP may
    be missing data while a VARIANCE cannot be explained that way. Assert the
    causal qualifier is present on each, not merely the two words.
    """
    block = _legend_block(_render(_template, True))
    assert "no statement submitted" in block
    assert "missing data rather than a discrepancy" in block
    assert "every declared account was submitted" in block


def test_legend_ties_high_confidence_to_both_checks(_template):
    """_compute_tier requires cash AND loan; the legend must not imply either alone."""
    block = _legend_block(_render(_template, True))
    assert "Cash position and loan activity both reconcile" in block


def test_legend_records_the_critical_coverage_demotion(_template):
    """The non-obvious branch of _compute_tier — an exact match can still be
    held below HIGH by a critical coverage gap."""
    assert "critical account-coverage gap" in _legend_block(_render(_template, True))


def test_legend_status_swatches_reuse_the_real_badge_classes(_template):
    """
    A legend that renders a different-looking badge than the table it explains
    is worse than no legend. These must be the SAME .rt-badge/.b-* classes the
    reconciliation table uses, not lookalike copies.
    """
    block = _legend_block(_render(_template, True))
    for cls in ("b-exact", "b-ok", "b-warn", "b-variance"):
        assert f'class="rt-badge {cls}"' in block, f"legend swatch not reusing .{cls}"


def test_legend_defines_evidence_types_including_direction_conflict(_template):
    block = _legend_block(_render(_template, True))
    assert "needs_review" in block
    assert "contradicted the direction of the amount" in block
    assert "flagged" in block


# ── PAR-150 boundary ────────────────────────────────────────────────────────

_VERDICT_WORDS = [
    "healthy", "unhealthy", "concerning", "concern", "risky",
    "good", "bad", "poor", "strong", "weak", "unacceptable", "suspicious",
    "abnormal", "favourable", "favorable", "unreasonable", "red flag",
    "material weakness", "fraud", "fraudulent",
]


def test_legend_carries_no_verdict_about_any_business(_template):
    """
    PAR-150 Rule 4, same boundary PAR-207's waterfall suite enforces: the legend
    defines the report's vocabulary and must never say what a figure means for
    this particular business.

    Note the words this list does NOT contain — "acceptable", "risk", "normal",
    "expected" — each appears legitimately as the NAME of a status the system
    emits ("Acceptable"), or inside the definition of one. Banning them here
    would make the legend unable to name the very things it exists to define.
    The verdict boundary is about applying a judgement to a deal, not about
    quoting a label.
    """
    blob = _visible_text(_legend_block(_render(_template, True)))
    for word in _VERDICT_WORDS:
        assert not re.search(rf"\b{re.escape(word)}\b", blob), (
            f"legend carries verdict word {word!r}"
        )


def test_legend_explicitly_hands_judgement_to_the_reviewer(_template):
    """Not just absence of a verdict — the panel says whose call it is."""
    block = _legend_block(_render(_template, True))
    assert "it draws no conclusion about this business" in block
    assert "the reviewer's call" in block


def test_legend_names_no_unreachable_external_specification(_template):
    """
    A reader holding this PDF cannot open an internal doc. The legend must not
    cite one — no ticket ids, no doc filenames — even though its own source
    comments reference them for maintainers.
    """
    block = _legend_block(_render(_template, True))
    assert not re.search(r"\bPAR-\d+\b", block)
    assert ".md" not in block


# ── regression: the legend is additive ──────────────────────────────────────

def test_no_pre_existing_section_was_displaced_recon_available(_template):
    html = _render(_template, True)
    for heading in _EXPECTED_HEADINGS_BOTH_STATES + _EXPECTED_HEADINGS_RECON_AVAILABLE:
        assert heading in html, f"PAR-206 displaced section: {heading!r}"


def test_no_pre_existing_section_was_displaced_recon_unavailable(_template):
    html = _render(_template, False)
    for heading in _EXPECTED_HEADINGS_BOTH_STATES + _EXPECTED_HEADINGS_RECON_UNAVAILABLE:
        assert heading in html, f"PAR-206 displaced section: {heading!r}"


@pytest.mark.parametrize("recon_available", [True, False])
def test_act_order_survives_the_insertion(_template, recon_available):
    html = _render(_template, recon_available)
    positions = [html.index(t) for t in (
        "Act 1 — Orientation", "Act 2 — Core Reconciliation",
        "Act 3 — Supporting Diagnostics", "Act 4 — Synthesis",
    )]
    assert positions == sorted(positions)
