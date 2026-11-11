"""Unified desktop entrypoint and review UI import cleanly on Python 3."""
from pathlib import Path

import pytest


def test_launcher_and_synoptic_gui_import():
    pytest.importorskip("PySide6")
    from afm_copilot.launcher import Launcher
    from afm_copilot.compare_gui import CompareWindow
    assert Launcher.__name__ == "Launcher"
    assert CompareWindow.__name__ == "CompareWindow"


def test_single_batch_entrypoint_launches_workstation():
    root = Path(__file__).resolve().parents[1]
    file = root / "AFM Copilot.bat"
    text = file.read_text(encoding="utf-8")
    assert "afm_copilot.launcher" in text
    assert "pythonw.exe" in text
    assert "git clean" not in text
    assert "git push" not in text
