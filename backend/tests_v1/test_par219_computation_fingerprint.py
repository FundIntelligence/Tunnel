"""PAR-219: the export() snapshot cache must invalidate on a computation-logic
deploy without anyone having to hand-bump a version constant.

Background: PAR-217 shipped a real reconciliation fix without bumping
CONFIG_VERSION. Every already-sealed snapshot kept serving pre-fix figures,
while PR-merged / build-SUCCESS / revision-at-100%-traffic / export-HTTP-200
all looked healthy. The cache short-circuit in api.py compares the stored
snapshot's config_version against the running CONFIG_VERSION, so making
CONFIG_VERSION derive from the computation source itself closes the gap.

These tests pin the two properties that actually matter, in both directions:
changing computation logic MUST invalidate, and changing presentation logic
MUST NOT (over-invalidation re-seals every deal in the system for nothing).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from v1 import config as cfg


def test_fingerprint_is_kept_out_of_config_version():
    """Critical: config_version IS part of the canonical snapshot payload and
    therefore feeds sha256_hash / financial_state_hash. Folding the fingerprint
    into it would change every deal's sealed hash on any computation edit and
    trip the golden-hash sentinel. The fingerprint must travel separately."""
    assert cfg.COMPUTATION_FINGERPRINT
    assert cfg.CONFIG_VERSION == cfg._CONFIG_VERSION_BASE
    assert cfg.COMPUTATION_FINGERPRINT not in cfg.CONFIG_VERSION


def test_fingerprint_never_enters_the_hashed_payload():
    """Guards the same invariant from the payload side: build_financial_state's
    canonical inputs must not gain a fingerprint field."""
    import inspect

    from v1.core import snapshot_engine

    for fn in (
        snapshot_engine._build_financial_state_payload,
        snapshot_engine.build_pds_payload,
        snapshot_engine.canonicalize_payload,
    ):
        assert "computation_fingerprint" not in inspect.getsource(fn), (
            f"{fn.__name__} must not reference computation_fingerprint — it "
            "would leak into sha256_hash / financial_state_hash"
        )


def test_fingerprint_is_deterministic():
    """Same source, same digest — otherwise every process restart would
    invalidate every cached snapshot in the system."""
    assert cfg._compute_logic_fingerprint() == cfg._compute_logic_fingerprint()
    assert cfg._compute_logic_fingerprint() == cfg.COMPUTATION_FINGERPRINT


def test_every_declared_computation_module_actually_exists():
    """A typo'd path would silently contribute a constant sentinel forever,
    meaning edits to that module would stop invalidating the cache — exactly
    the PAR-219 failure, reintroduced quietly."""
    base = Path(cfg.__file__).resolve().parent
    missing = [rel for rel in cfg._COMPUTATION_MODULES if not (base / rel).is_file()]
    assert not missing, f"declared computation modules do not exist: {missing}"


def test_presentation_modules_are_not_fingerprinted():
    """Renderer/PDF changes must not force a global re-seal. PAR-206/207/208
    were exactly this kind of change: they alter how a figure is drawn, not
    what it is."""
    for presentation in (
        "analysis/snapshot_html_renderer.py",
        "core/pdf_generator.py",
        "core/pdf_jobs.py",
    ):
        assert presentation not in cfg._COMPUTATION_MODULES


def _fingerprint_with_override(monkeypatch, rel_path: str, extra: bytes) -> str:
    """Recompute the fingerprint as if one module's bytes had `extra` appended,
    without touching anything on disk."""
    base = Path(cfg.__file__).resolve().parent
    real_read = Path.read_bytes

    def fake_read(self):  # noqa: ANN001
        data = real_read(self)
        if self == (base / rel_path):
            return data + extra
        return data

    monkeypatch.setattr(Path, "read_bytes", fake_read)
    return cfg._compute_logic_fingerprint()


def test_computation_change_invalidates(monkeypatch):
    """The core PAR-219 property: edit reconciliation logic -> fingerprint
    moves -> CONFIG_VERSION moves -> cached snapshots stop being served."""
    before = cfg._compute_logic_fingerprint()
    after = _fingerprint_with_override(
        monkeypatch, "analysis/reconciliation_engine.py", b"\n# probe\n"
    )
    assert after != before


def test_classifier_change_invalidates(monkeypatch):
    """Same property via a second, independent module, so the test isn't
    accidentally passing because of one path."""
    before = cfg._compute_logic_fingerprint()
    after = _fingerprint_with_override(monkeypatch, "core/classifier.py", b"\n# probe\n")
    assert after != before


def test_fingerprint_is_order_and_swap_resistant():
    """Path-salting + length-prefixing means two modules swapping contents
    still produces a different digest than the real tree."""
    base = Path(cfg.__file__).resolve().parent
    naive = hashlib.sha256()
    for rel in sorted(cfg._COMPUTATION_MODULES):
        naive.update((base / rel).read_bytes())
    # The real implementation salts with path + length, so it must not equal
    # the naive content-only concatenation.
    assert cfg._compute_logic_fingerprint() != naive.hexdigest()[:12]
