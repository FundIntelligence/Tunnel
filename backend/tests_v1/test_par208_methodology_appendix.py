"""
PAR-208 — methodology appendix (Act 4).

Documentation/disclosure only: no computation logic changed. These tests pin
the two things that make a methodology note trustworthy rather than harmful:

  1. It describes what the code ACTUALLY does. Every claim in the appendix was
     checked against the real implementation on 2026-08-31:
       fiscal window     reconciliation_engine._get_fiscal_year_transactions()
                         + calculate_cash_position_reconciliation()
       entity resolution core/entities.py build_entities()/_clean_display_name()
       transfer matching core/transfer_matcher.py match_transfers()
       classification    core/classifier.py classify_with_reason()

  2. It never evaluates a deal. Same boundary as PAR-206/PAR-207: describe HOW
     a number was computed, never WHAT it means here.

The transfer paragraph is deliberately driven off the deal's real
InterAccountTransfer state rather than hardcoded "not active", so the document
stops making that claim automatically if PAR-102 ships. Verified against live
prod 2026-08-31 (PAR-102 still open, status Backlog): 0 transactions tagged
transfer/internal_transfer, 0 rows in pds_transfer_links, and exactly 1
distinct account_id across all 193,327 rows of pds_raw_transactions — so the
UNAVAILABLE branch is what every deal renders today.
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

from backend.v1.analysis.snapshot_context import InterAccountTransfer
from backend.v1.analysis.snapshot_html_renderer import _inter_account_transfer_ctx_from

_TEMPLATES_DIR = os.path.join(_BACKEND, "v1", "templates")


@pytest.fixture(scope="module")
def template():
    return Environment(loader=FileSystemLoader(_TEMPLATES_DIR)).get_template("snapshot.html")


@pytest.fixture(scope="module")
def raw_template():
    with open(os.path.join(_TEMPLATES_DIR, "snapshot.html")) as fh:
        return fh.read()


def _ctx(recon_available=True, transfer_state="UNAVAILABLE"):
    return dict(
        view="observed_recon", partner_name=None, company_name="Test Co",
        sector="Trade", period_label="Jan-Dec 2025", generated_date="2026-08-31",
        analyst_notes="", report_id="RPT-1", sha256_hash="a" * 64,
        qr_svg="<svg></svg>", verify_url="https://x", currency="KES",
        recon_available=recon_available, recon_tier="LOW_CONFIDENCE",
        vp_confidence_color="warning", loan_recon_label="Variance",
        tier_badge_class="tier-low", tier_badge_text="Observed",
        data_source_pills=[], data_source_note="", total_txn_count=12851,
        kms=[], cashflow_rows=[], cashflow_note="",
        cashflow_peak_trough_note="", cashflow_trend_note="",
        inflow_total_str="KES 1", inflow_segments=[], inflow_warn="",
        outflow_total_str="KES 1", outflow_segments=[], outflow_warn="",
        tax_count=0, tax_freq_str="--", tax_penalty_count=0, tax_jan_spike_str="",
        tax_total_str="KES 0", tax_note="",
        loan_disbursed_str="KES 0", loan_repaid_str="KES 0", loan_net_str="0",
        loan_freq_str="--", loan_facility_count=0, loan_facilities=[],
        loan_recon_status="", loan_bank_net_str="KES 0",
        loan_declared_net_str="KES 0", loan_variance_str="0%",
        recon_rows=[], recon_fiscal_note="", patterns=[],
        account_coverage={"available": False, "note": ""},
        inventory={"available": False, "financial_year": "", "note": ""},
        supplier_payments={"available": False},
        tax_compliance={"total_str": "KES 0", "n_tax_months": 0,
                         "n_total_months": 0, "kra_compliance": "NOT_DETECTED",
                         "clause": ""},
        transaction_patterns={"critical_count": 0, "high_count": 0,
                               "total_flagged": 0, "total_txn_count": 0, "clause": ""},
        inter_account_transfer={"badge_label": "Not Available", "pairs": [],
                                 "note": "", "override_note": "",
                                 "state": transfer_state},
        risk_assessment={"tier": "LOW_CONFIDENCE", "advisory_tier": "--",
                          "missing_pct": "--", "largest_rev_pct_str": "--",
                          "anomaly_summary": "", "conclusion": "", "transfer_note": ""},
    )


def _appendix_html(html):
    start = html.index('<div class="appendix">')
    end = html.index("</div>", html.index('class="appendix-foot"', start))
    return html[start:end]


# ── the semantic state must actually reach the template ─────────────────────

@pytest.mark.parametrize("state", ["DETECTED", "NO_TRANSFERS_FOUND", "UNAVAILABLE"])
def test_renderer_passes_transfer_state_through(state):
    """PAR-208 relies on the raw state, not just the badge label."""
    iat = InterAccountTransfer(state=state, pairs=[], pair_count=0, total=None,
                               note="n", override_note="o", manual_override_count=0)
    assert _inter_account_transfer_ctx_from(iat)["state"] == state


# ── placement ───────────────────────────────────────────────────────────────

def test_appendix_closes_act_4(template):
    html = template.render(**_ctx())
    i_act4 = html.index("Act 4 — Synthesis")
    i_notes = html.index('>Analyst Notes <span')
    i_risk = html.index('>Risk Assessment Summary <span')
    i_appx = html.index("Methodology appendix")
    i_end = html.index("end page-body", i_act4)
    assert i_act4 < i_notes < i_risk < i_appx < i_end


@pytest.mark.parametrize("recon_available", [True, False])
def test_appendix_renders_exactly_once_in_both_states(template, recon_available):
    html = template.render(**_ctx(recon_available=recon_available))
    assert html.count('<div class="appendix">') == 1


# ── accuracy: the transfer paragraph must match reality ─────────────────────

def test_unavailable_state_says_check_is_not_running(template):
    """
    The condition verified against live prod on 2026-08-31. Describing the
    matching rule as if it were running would misrepresent the report.
    """
    html = template.render(**_ctx(transfer_state="UNAVAILABLE"))
    appx = _appendix_html(html)
    assert "This check is not currently active for any deal." in appx
    assert "Inter-Account Transfer Analysis" in appx  # points at the section that explains why
    # and it must say what that means for the figures, not leave it implicit
    assert "gross" in appx


@pytest.mark.parametrize("state", ["DETECTED", "NO_TRANSFERS_FOUND"])
def test_active_states_do_not_claim_the_check_is_dead(template, state):
    html = template.render(**_ctx(transfer_state=state))
    appx = _appendix_html(html)
    assert "not currently active" not in appx


@pytest.mark.parametrize("state", ["DETECTED", "NO_TRANSFERS_FOUND", "UNAVAILABLE"])
def test_matching_rule_parameters_are_stated_in_every_branch(template, state):
    """The 2-day window is the actual match_transfers() parameter."""
    html = template.render(**_ctx(transfer_state=state))
    appx = _appendix_html(html)
    assert '<span class="appendix-val">2 calendar days</span>' in appx
    assert "opposite sign" in appx
    assert "same amount" in appx
    assert "different accounts" in appx


# ── accuracy: the other three items ─────────────────────────────────────────

def test_fiscal_filtering_describes_declared_year_not_statement_range(template):
    appx = _appendix_html(template.render(**_ctx()))
    assert "financial_year_start" in appx and "financial_year_end" in appx
    assert "not the date range of the bank statements" in appx
    assert "excluded" in appx


def test_entity_resolution_is_summary_level_and_deal_scoped(template):
    appx = _appendix_html(template.render(**_ctx()))
    assert "normalisation rules" in appx
    assert "no counterparty identity is carried across deals" in appx
    # summary level only — must not leak implementation detail
    for leak in ("sha256", "entity_id", "_clean_display_name", "regex", "MPESAC2B"):
        assert leak.lower() not in appx.lower(), f"implementation detail leaked: {leak}"


def test_classification_summary_is_brief_and_does_not_duplicate_the_trigger_table(template):
    appx = _appendix_html(template.render(**_ctx()))
    assert '<span class="appendix-val">needs_review</span>' in appx
    assert '<span class="appendix-val">other</span>' in appx
    # brevity: the classification paragraph stays short (2-3 sentences)
    para = appx[appx.index("Classification: classified"):]
    body = para[para.index('class="appendix-body"'):]
    body = re.sub(r"<[^>]+>", " ", body[: body.index("</div>")])
    assert body.count(".") <= 4, f"classification note too long: {body.count('.')} sentences"
    # must NOT reproduce the canonical trigger_reason table
    for reason in ("fallback:large_positive_no_keyword_match", "direction_conflict:",
                   "keyword_match:", "is_transfer:flag"):
        assert reason not in appx, f"canonical trigger_reason leaked: {reason}"


# ── the boundary: no verdicts ───────────────────────────────────────────────

_VERDICT_WORDS = [
    "healthy", "unhealthy", "concerning", "concern", "risky", "strong", "weak",
    "poor", "suspicious", "abnormal", "favourable", "favorable", "red flag",
    "worrying", "reassuring", "well-managed", "well managed", "solid", "robust",
    "good", "bad", "acceptable", "unacceptable", "normal",
]


@pytest.mark.parametrize("state", ["DETECTED", "NO_TRANSFERS_FOUND", "UNAVAILABLE"])
def test_appendix_carries_no_verdict_about_the_deal(template, state):
    appx = _appendix_html(template.render(**_ctx(transfer_state=state)))
    text = re.sub(r"<[^>]+>", " ", appx).lower()
    for word in _VERDICT_WORDS:
        assert not re.search(rf"\b{re.escape(word)}\b", text), \
            f"appendix carries verdict word {word!r} in state {state}"


def test_appendix_states_it_makes_no_assessment(template):
    appx = _appendix_html(template.render(**_ctx()))
    assert "makes no assessment of this business" in appx


# ── design system ───────────────────────────────────────────────────────────

def test_appendix_uses_no_bold_rendering_tags(template):
    """
    <strong>/<b> render bold via the UA stylesheet regardless of CSS class,
    which breaks the document's never-bold type rule.
    """
    html = template.render(**_ctx())
    appx = _appendix_html(html).lower()
    for tag in ("<strong", "<b>", "<b ", "<h1", "<h2", "<h3"):
        assert tag not in appx, f"bold/heading tag {tag!r} in appendix"


def test_appendix_css_respects_the_type_rules(raw_template):
    css = raw_template[: raw_template.index("</style>")]
    block = css[css.index("/* ── METHODOLOGY APPENDIX"): css.index("/* ── GAP WATERFALL")]
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)   # drop comments

    weights = [int(w) for w in re.findall(r"font-weight:\s*(\d+)", block)]
    assert weights and max(weights) <= 500, f"bold weight in appendix CSS: {weights}"

    # semantic colours are meaning-locked; an appendix states method, not status
    for token in ("--green", "--amber", "--red"):
        assert token not in block, f"{token} used decoratively in appendix CSS"

    title = block[block.index(".appendix-title"):]
    title = title[: title.index("}")]
    assert "var(--serif)" in title
    assert "font-weight: 400" in title
    assert "text-transform" not in title     # never all-caps

    body = block[block.index(".appendix-body"):]
    body = body[: body.index("}")]
    assert "var(--sans)" in body and "font-weight: 300" in body

    val = block[block.index(".appendix-val"):]
    val = val[: val.index("}")]
    assert "var(--mono)" in val


@pytest.mark.parametrize("family,weight", [("IBM Plex Serif", 400), ("IBM Plex Sans", 300)])
def test_weights_the_appendix_relies_on_are_self_hosted(raw_template, family, weight):
    """A weight with no @font-face would silently fall back to a synthetic face."""
    css = raw_template[: raw_template.index("</style>")]
    pattern = (r"@font-face\s*\{[^}]*?font-family:\s*'" + re.escape(family)
               + r"'[^}]*?font-weight:\s*" + str(weight) + r"[^}]*?\}")
    assert re.search(pattern, css, re.S), f"{family} {weight} is not self-hosted"
