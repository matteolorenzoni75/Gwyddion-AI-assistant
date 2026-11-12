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


def test_symmetric_cards_have_explanations_and_tooltips():
    pytest.importorskip("PySide6")
    from afm_copilot.launcher import WORKFLOW_ACTIONS, MAINTENANCE_ACTIONS
    from PySide6.QtWidgets import QApplication, QToolButton
    from afm_copilot.launcher import Launcher
    assert len(WORKFLOW_ACTIONS) == 4
    assert len(MAINTENANCE_ACTIONS) == 8
    for name, brief, detail, target, icon_name in (*WORKFLOW_ACTIONS,
                                                    *MAINTENANCE_ACTIONS):
        assert name and brief and len(detail) > 40
        assert icon_name.startswith("SP_")
    app = QApplication.instance() or QApplication([])
    win = Launcher()
    try:
        assert len(win.action_buttons) == 12
        helps = win.findChildren(QToolButton, "helpButton")
        assert len(helps) == 12
        help_widget = helps[0]
        help_widget.setChecked(True)
        assert help_widget.isChecked()
        assert win.output.isReadOnly()
        assert hasattr(win, "_location_report")
        assert win._location_report["summary"]["full_archive_rescanned"] is False
        from PySide6.QtWidgets import QLabel
        labels = [item.text() for item in win.findChildren(QLabel)]
        assert any("Gwyddion 32-bit" in item and "PyGwy" in item for item in labels)
        assert "CARTELLE IMMAGINI" in labels
        assert labels.index("CARTELLE IMMAGINI") > labels.index("ARCHIVIO E MANUTENZIONE")
        assert "Codice AFM Copilot" not in labels
        assert "Database labeling esperto" not in labels
        assert "Indice correzioni manuali" not in labels
    finally:
        win.close()
