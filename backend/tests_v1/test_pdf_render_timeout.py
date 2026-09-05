"""
Timeout enforcement for PDF rendering (PAR-183).

An earlier fix (PAR-160 follow-up, commit 1ba7cf3) was written but never
merged — the endpoints called weasyprint.HTML(...).write_pdf() directly,
unbounded, right up until this fix. Separately, that earlier attempt used
ThreadPoolExecutor.submit + future.result(timeout=...), which does not
actually stop a blocking synchronous render: the worker thread keeps running
to completion after the timeout fires, permanently tying up a pool slot.
_render_html_to_pdf (api.py) instead runs the render in a real OS process
so it can be SIGKILL'd on timeout.

This suite drives _render_html_to_pdf directly against a stubbed
`weasyprint` module (real WeasyPrint isn't installed in every dev/test env)
covering: a fast render completing well under the timeout, and a slow
render actually being killed rather than left to finish in the background.

Run:
    cd backend
    python3 -m pytest tests_v1/test_pdf_render_timeout.py -v
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ROOT = os.path.abspath(os.path.join(_BACKEND, os.pardir))
for p in (_BACKEND, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import HTTPException

from backend.v1 import api as api_module


def _install_weasyprint_stub(write_pdf_impl):
    """Stub `weasyprint.HTML(...).write_pdf()`. Because the render runs in a
    forked child process, the stub must be picklable-by-fork (fork inherits
    sys.modules directly, no pickling involved) and self-contained — it
    cannot close over test-instance state, only plain values/callables."""
    stub = types.ModuleType("weasyprint")

    class _StubDoc:
        def write_pdf(self):
            return write_pdf_impl()

    stub.HTML = lambda *a, **kw: _StubDoc()
    return patch.dict(sys.modules, {"weasyprint": stub})


class TestPdfRenderTimeout(unittest.TestCase):
    def setUp(self):
        # Keep the whole suite fast — real production value is 45s.
        self._timeout_patch = patch.object(api_module, "_PDF_RENDER_TIMEOUT_S", 1)
        self._timeout_patch.start()
        self.addCleanup(self._timeout_patch.stop)

    def test_fast_render_succeeds_under_timeout(self):
        with _install_weasyprint_stub(lambda: b"%PDF-fast"):
            pdf_bytes = api_module._render_html_to_pdf("<html></html>", "deal-fast")
        self.assertEqual(pdf_bytes, b"%PDF-fast")

    def test_slow_render_times_out_with_clear_error(self):
        def _slow():
            import time
            time.sleep(10)  # far past the 1s patched timeout
            return b"%PDF-too-late"

        with _install_weasyprint_stub(_slow):
            with self.assertRaises(HTTPException) as ctx:
                api_module._render_html_to_pdf("<html></html>", "deal-slow")

        exc = ctx.exception
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(exc.detail["error_code"], "PDF_GENERATION_TIMEOUT")
        self.assertIn("deal-slow", exc.detail["error_message"])
        self.assertIn("snapshot/html", exc.detail["error_message"])
        self.assertIn("transactions", exc.detail["error_message"])

    def test_render_failure_surfaces_as_internal_error_not_a_hang(self):
        def _boom():
            raise RuntimeError("weasyprint blew up")

        with _install_weasyprint_stub(_boom):
            with self.assertRaises(HTTPException) as ctx:
                api_module._render_html_to_pdf("<html></html>", "deal-broken")

        exc = ctx.exception
        self.assertEqual(exc.status_code, 500)
        self.assertEqual(exc.detail["error_code"], "INTERNAL")


if __name__ == "__main__":
    unittest.main()
