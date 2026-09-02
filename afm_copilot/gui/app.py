"""
The main window.

Deliberately thin. It owns the viewer and the log, creates one dock per
registered panel, and hands every panel the same context. It knows nothing
about recipes, profiles or measurement -- that is what keeps the future slots
cheap to fill.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QMainWindow,
                               QMessageBox, QPlainTextEdit, QStatusBar,
                               QVBoxLayout, QWidget)

from afm_copilot import __version__
from afm_copilot.bridge import BridgeError, GwyBridge
from afm_copilot.gui.panels import PANELS, AppContext
from afm_copilot.gui.panels.profile import ProfilePanel
from afm_copilot.gui.panels.scans import ScansPanel
from afm_copilot.gui.viewer import ScanViewer
from afm_copilot.gui.workers import TaskRunner

DOCK_AREAS = {
    "left": Qt.LeftDockWidgetArea,
    "right": Qt.RightDockWidgetArea,
    "bottom": Qt.BottomDockWidgetArea,
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"AFM Copilot {__version__}")
        self.resize(1500, 950)

        work_dir = Path(tempfile.gettempdir()) / "afm_copilot_gui"
        work_dir.mkdir(parents=True, exist_ok=True)

        self.runner = TaskRunner()
        self.ctx = AppContext(runner=self.runner, log=self.log,
                              work_dir=work_dir)

        self._build_central()
        self._build_log()
        self._build_panels()
        self._build_menus()

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

        self.ctx.on_channel_changed(lambda ch, path: self.viewer.show_channel(ch))
        self.log(f"AFM Copilot {__version__}. Working folder: {work_dir}")
        self._check_gwyddion()

    # ------------------------------------------------------------ building
    def _build_central(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer = ScanViewer()
        layout.addWidget(self.viewer)
        self.setCentralWidget(central)

    def _build_log(self) -> None:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        self.log_view.setStyleSheet("font-family: Consolas, monospace; "
                                    "font-size: 11px;")
        dock = QDockWidget("Log", self)
        dock.setObjectName("dock_log")
        dock.setWidget(self.log_view)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.log_dock = dock

    def _build_panels(self) -> None:
        self.panels = {}
        self.panel_docks = {}
        bottom_docks = []

        for cls in PANELS:
            panel = cls(self.ctx, self)
            dock = QDockWidget(cls.title, self)
            dock.setObjectName(f"dock_{cls.__name__}")
            dock.setWidget(panel)
            self.addDockWidget(DOCK_AREAS.get(cls.area, Qt.RightDockWidgetArea),
                               dock)
            self.panels[cls.__name__] = panel
            self.panel_docks[cls.__name__] = dock

            if cls.area == "bottom":
                bottom_docks.append(dock)
            if not cls.available:
                dock.setStyleSheet("QDockWidget::title { color: palette(mid); }")

        # The scans panel is looked up by name from other panels; naming it
        # here keeps that lookup from reaching into the registry.
        self.scans_panel = self.panels.get(ScansPanel.__name__)

        # Stack the planned panels behind the working ones rather than letting
        # them take space from what is usable today.
        right = [d for cls, d in zip(PANELS, self.panel_docks.values())
                 if cls.area == "right"]
        for dock in right[1:]:
            self.tabifyDockWidget(right[0], dock)
        if right:
            right[0].raise_()

        for dock in bottom_docks:
            self.tabifyDockWidget(self.log_dock, dock)
            dock.raise_()

        profile = self.panels.get(ProfilePanel.__name__)
        if profile is not None:
            self.viewer.profile_moved.connect(profile.set_line_pixels)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open folder...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(
            lambda: self.scans_panel.choose_folder() if self.scans_panel else None)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        for name, dock in self.panel_docks.items():
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        view_menu.addAction(self.log_dock.toggleViewAction())

        tools_menu = self.menuBar().addMenu("&Tools")
        check = QAction("Check Gwyddion connection", self)
        check.triggered.connect(lambda: self._check_gwyddion(verbose=True))
        tools_menu.addAction(check)

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("About", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    # -------------------------------------------------------------- events
    def log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"{stamp}  {message}")

    def _check_gwyddion(self, verbose: bool = False) -> None:
        def check():
            return GwyBridge().self_test()

        def ok(result):
            msg = (f"Gwyddion {result.get('gwy_version')} ready "
                   f"(via Python {result.get('python_version')})")
            self.statusBar().showMessage(msg)
            self.log(msg)
            if verbose:
                QMessageBox.information(self, "Gwyddion connection", msg)

        def failed(_desc, message):
            self.statusBar().showMessage("Gwyddion unavailable")
            self.log(f"Gwyddion unavailable: {message}")
            QMessageBox.warning(
                self, "Gwyddion unavailable",
                f"{message}\n\nProcessing will not work until this is fixed. "
                f"Viewing already-converted .gwy files still will.")

        self.runner.submit("Checking Gwyddion", check,
                           on_result=ok, on_failed=failed)

    def _about(self) -> None:
        QMessageBox.about(
            self, "AFM Copilot",
            f"<b>AFM Copilot {__version__}</b>"
            "<p>Makes Gwyddion's capability reachable without knowing it.</p>"
            "<p>Processing runs through Gwyddion itself, in a Python 2.7 "
            "subprocess. The same operations are available to Claude Desktop "
            "over MCP.</p>")

    def closeEvent(self, event) -> None:
        if self.runner.busy:
            answer = QMessageBox.question(
                self, "Still working",
                "A task is still running. Quit anyway?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.runner.wait(2000)
        event.accept()


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AFM Copilot")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
