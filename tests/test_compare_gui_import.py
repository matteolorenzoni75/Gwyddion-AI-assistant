"""Comparison import must not mistake IBW bytes for a native GWY file."""
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_raw_ibw_goes_directly_to_bridge_not_gwy_parser(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    import afm_copilot.compare_gui as module
    raw = tmp_path / "source.ibw"
    raw.write_bytes(b"raw instrument file")
    calls = []

    def native(_path):
        calls.append("gwy")
        raise AssertionError("invalid gwy header")

    def importer(path, workdir):
        calls.append("bridge")
        return "height channel", {"source": "bridge"}

    monkeypatch.setattr(module, "load_height", native)
    monkeypatch.setattr(module, "_load", importer)
    viewer = SimpleNamespace(work_dir=tmp_path / "work")
    value, _ = module.CompareWindow._channel(viewer, raw)
    assert value == "height channel"
    assert calls == ["bridge"]


def test_corrected_nonstandard_suffix_first_checks_gwyddion(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    import afm_copilot.compare_gui as module
    corrected = tmp_path / "sample.ibw corrected with facet"
    corrected.write_bytes(b"GWYP")
    calls = []
    monkeypatch.setattr(
        module, "load_height",
        lambda path: calls.append("gwy") or "corrected topography")

    def cannot_import(*args):
        raise AssertionError("must not use the instrument bridge here")

    monkeypatch.setattr(module, "_load", cannot_import)
    viewer = SimpleNamespace(work_dir=tmp_path / "work")
    channel, _ = module.CompareWindow._channel(
        viewer, corrected, operator_corrected=True)
    assert channel == "corrected topography"
    assert calls == ["gwy"]


def test_corrected_false_gwy_header_can_fallback_to_bridge(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    import afm_copilot.compare_gui as module
    corrected = tmp_path / "sample corrected.ibw"
    corrected.write_bytes(b"not gwy")
    monkeypatch.setattr(
        module, "load_height",
        lambda path: (_ for _ in ()).throw(AssertionError("bad gwy header")))
    monkeypatch.setattr(
        module, "_load", lambda path, workdir: ("from bridge", {}))
    viewer = SimpleNamespace(work_dir=tmp_path / "work")
    channel, _ = module.CompareWindow._channel(
        viewer, corrected, operator_corrected=True)
    assert channel == "from bridge"


def test_missing_auto_is_not_misdiagnosed_as_missing_original():
    pytest.importorskip("PySide6")
    from afm_copilot.compare_gui import CompareWindow
    assert "not" in CompareWindow._status_for(
        None, {"original": "C:/raw.ibw", "manual": "C:/corrected.gwy",
               "automated": None}, "automated").lower()
