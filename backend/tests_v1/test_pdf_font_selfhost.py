"""
Self-hosted fonts in the snapshot template (PAR-177).

Root cause: snapshot.html's <style> block did a live @import of Google
Fonts CSS (+ 10 separate woff2/ttf files from fonts.gstatic.com), fetched
synchronously inside weasyprint.write_pdf() on every single PDF render --
measured at ~13s of pure network cost on a document with zero transaction
data, and reproducing regardless of deal size (PAR-183's forked-process
timeout fix has no cross-request font cache, so every render paid this in
full). On Cloud Run this plausibly explains the 81-465s timeouts seen on
GET /snapshot/pdf. Fix: base64-embed the exact IBM Plex family/weight/style
set previously pulled via @import, removing the external network
dependency entirely for both /snapshot/html and /snapshot/pdf.

This suite checks (a) statically, that no Google Fonts reference remains
in the shipped template, and (b) with a real WeasyPrint render (network
sockets blocked at the socket.socket level) that PDF generation actually
succeeds without any external fetch -- both for a small stub deal and for
a Deed-Technologies-shaped deal (3,059 txns / 6 months / 1 account, the
real deal that originally timed out under PAR-177).

Run:
    cd backend
    python3 -m pytest tests_v1/test_pdf_font_selfhost.py -v
"""
import os
import socket
import time
import unittest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_TEMPLATE_PATH = os.path.join(_BACKEND, "v1", "templates", "snapshot.html")

try:
    import weasyprint  # noqa: F401
    from jinja2 import Environment, FileSystemLoader
    _RENDER_DEPS_AVAILABLE = True
except ImportError:
    _RENDER_DEPS_AVAILABLE = False


def _stub_context(total_txn_count: int, months: int, accounts: int):
    return dict(
        view="observed_recon", partner_name=None, company_name="Test Co",
        sector="--", period_label="period", generated_date="2026-08-18",
        analyst_notes="", report_id="RPT-TEST", sha256_hash="a" * 64,
        qr_svg="<svg></svg>", verify_url="https://parity.example/verify/x",
        currency="KES", recon_available=True, recon_tier="MEDIUM_CONFIDENCE",
        vp_confidence_color="#C8960C", loan_recon_label="Partial",
        tier_badge_class="amber", tier_badge_text="Medium",
        data_source_pills=[{"label": f"Bank · {total_txn_count} txns", "active": True}],
        data_source_note=f"{accounts} account(s), {months} months",
        total_txn_count=total_txn_count,
        kms=[{"label": "Avg monthly inflow", "value": "KES 4.2M"}] * 4,
        cashflow_rows=[
            {"month": f"2026-{(m % 12) + 1:02d}", "inflow": "1,000,000",
             "outflow": "800,000", "net": "200,000"}
            for m in range(months)
        ],
        cashflow_note="", cashflow_peak_trough_note="", cashflow_trend_note="",
        inflow_total_str="KES 25.2M", inflow_segments=[{"label": "Sales", "pct": 60}],
        inflow_warn=False,
        outflow_total_str="KES 20.1M", outflow_segments=[{"label": "Payroll", "pct": 40}],
        outflow_warn=False,
        tax_count=42, tax_freq_str="monthly", tax_penalty_count=0,
        tax_jan_spike_str="--", tax_total_str="KES 1.1M", tax_note="",
        loan_disbursed_str="KES 0", loan_repaid_str="KES 0", loan_net_str="KES 0",
        loan_freq_str="0.0 txns / month", loan_facility_count=0, loan_facilities=[],
        loan_recon_status="N/A", loan_bank_net_str="--", loan_declared_net_str="--",
        loan_variance_str="--",
        recon_rows=[{"label": "Cash position", "status": "OK"}],
        recon_fiscal_note="",
        patterns=[{"label": "Round-number payments", "severity": "low"}],
        account_coverage={
            "available": True,
            "accounts": [{"name": f"Bank ****{i}", "status": "OK"} for i in range(accounts)],
            "coverage_pct": 100, "advisory_tier": "OK",
        },
        inventory={"available": False}, supplier_payments={"available": False},
        tax_compliance={"available": False},
        transaction_patterns={
            "critical_count": 0, "high_count": 1, "total_flagged": 3,
            "total_txn_count": total_txn_count, "clause": "--",
        },
        inter_account_transfer={"pairs": []},
        risk_assessment={
            "tier": "MEDIUM_CONFIDENCE", "advisory_tier": "OK", "missing_pct": "--",
            "largest_rev_pct_str": "18.4%", "anomaly_summary": "--",
            "conclusion": "--", "transfer_note": "--",
        },
    )


class _BlockNetwork:
    """Blocks all outbound socket creation for the duration of the block,
    to prove no external fetch happens during PDF generation."""

    def __enter__(self):
        self._orig_socket = socket.socket

        def _blocked(*args, **kwargs):
            raise RuntimeError("network access blocked for clean-room test")

        socket.socket = _blocked
        return self

    def __exit__(self, *exc):
        socket.socket = self._orig_socket


class TestSnapshotTemplateHasNoExternalFontDependency(unittest.TestCase):
    def setUp(self):
        with open(_TEMPLATE_PATH, "r") as f:
            self.template_src = f.read()

    def test_no_google_fonts_import_or_url(self):
        # The domain name may still appear in an explanatory code comment;
        # what matters is that no @import rule or url() actually fetches
        # from it (the only thing that would trigger a network request).
        self.assertNotIn("@import url(", self.template_src)
        self.assertNotIn("url(https://fonts.googleapis.com", self.template_src)
        self.assertNotIn("url(https://fonts.gstatic.com", self.template_src)

    def test_expected_font_faces_embedded(self):
        # Matches the exact prior @import spec: IBM Plex Serif
        # ital,wght@0,300;0,400;0,500;1,400 (4) + Sans wght@300;400;500;600
        # (4) + Mono wght@400;500 (2) = 10 font files.
        self.assertEqual(self.template_src.count("@font-face"), 10)
        for family in ("IBM Plex Serif", "IBM Plex Sans", "IBM Plex Mono"):
            self.assertIn(family, self.template_src)
        self.assertIn("data:font/ttf;base64,", self.template_src)


@unittest.skipUnless(_RENDER_DEPS_AVAILABLE, "weasyprint/jinja2 not installed in this env")
class TestPdfRenderIsNetworkFree(unittest.TestCase):
    def setUp(self):
        env = Environment(loader=FileSystemLoader(os.path.dirname(_TEMPLATE_PATH)))
        self.template = env.get_template(os.path.basename(_TEMPLATE_PATH))

    def _render_pdf(self, context, network_blocked=True):
        html = self.template.render(**context)
        ctx = _BlockNetwork() if network_blocked else _nullcontext()
        with ctx:
            t0 = time.perf_counter()
            pdf_bytes = weasyprint.HTML(string=html).write_pdf()
            elapsed = time.perf_counter() - t0
        return pdf_bytes, elapsed

    def test_small_deal_pdf_succeeds_offline_and_fast(self):
        pdf_bytes, elapsed = self._render_pdf(_stub_context(30, months=2, accounts=1))
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        # Generous CI-safe ceiling -- local measurement was ~7-8s, dominated
        # by decoding the embedded fonts once, not by content size.
        self.assertLess(elapsed, 30, f"small-deal render took {elapsed:.1f}s offline")

    def test_deed_scale_deal_pdf_succeeds_offline_and_fast(self):
        # Deed Technologies' real shape: 3,059 transactions but only 6
        # distinct months and 1 account -- confirms the fix holds at the
        # deal that originally timed out at 81-465s.
        pdf_bytes, elapsed = self._render_pdf(_stub_context(3059, months=6, accounts=1))
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertLess(elapsed, 30, f"Deed-scale render took {elapsed:.1f}s offline")


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


if __name__ == "__main__":
    unittest.main()
