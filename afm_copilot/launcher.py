"""Unified AFM Copilot local workstation launcher.

Starts the existing main GUI, expert labeler, and three-way comparison.
Maintenance tasks run as explicit subprocesses with visible output; no
automatic full archive scan, raw cleanup, deployment or Git commit.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QPlainTextEdit, QVBoxLayout, QWidget,
)

from afm_copilot.feedback import PROJECT_ROOT


class Launcher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AFM Copilot — Workstation")
        self.resize(820, 640)
        self.process = None
        body = QWidget()
        layout = QVBoxLayout(body)
        heading = QLabel("AFM Copilot  |  Local scientific workstation")
        heading.setStyleSheet("font-size: 19px; font-weight: 600;")
        layout.addWidget(heading)
        layout.addWidget(QLabel(
            "Topography first · Preserve all AFM channels · "
            "Raw and operator labels never leave this PC"))
        for title, module in (
            ("1 · AFM Copilot — elaborazione", "afm_copilot.gui"),
            ("2 · Expert Labeler — separato ma integrato", "afm_copilot.labeler"),
            ("3 · Confronto sinottico originale / manuale / automatico",
             "afm_copilot.compare_gui"),
        ):
            btn = QPushButton(title)
            btn.setMinimumHeight(44)
            btn.clicked.connect(lambda _=False, m=module: self._launch(m))
            layout.addWidget(btn)
        layout.addWidget(QLabel("Archivio e ricerca delle tue correzioni"))
        for label, args in (
            ("Cerca versioni corrette manualmente — analisi locale",
             ("-m", "afm_copilot.manual_pairs")),
            ("Archivio AFM — SOLO anteprima (calcola checksum)",
             ("-m", "afm_copilot.archive_organizer")),
            ("Diagnostica repository Git",
             ("-m", "afm_copilot.maintenance", "status")),
            ("Anteprima pulizia cache locali",
             ("-m", "afm_copilot.maintenance", "clean-preview")),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, a=args: self._task(a))
            layout.addWidget(button)
        row = QHBoxLayout()
        cache = QPushButton("Pulisci SOLO cache temporanee")
        cache.clicked.connect(self._clean)
        row.addWidget(cache)
        push = QPushButton("Push Git — dev/image-wizard")
        push.clicked.connect(self._push)
        row.addWidget(push)
        layout.addLayout(row)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Output delle operazioni locali, senza nomi di scansioni.")
        layout.addWidget(self.output, 1)
        self.setCentralWidget(body)

    def _launch(self, module):
        # Use pythonw for child GUIs; no Python 2.7 PATH ambiguity.
        executable = Path(sys.executable)
        if executable.name.lower() == "python.exe":
            possible = executable.with_name("pythonw.exe")
            if possible.exists():
                executable = possible
        subprocess.Popen([str(executable), "-m", module], cwd=str(PROJECT_ROOT),
                         close_fds=True)
        self.output.appendPlainText("Avviata: " + module)

    def _task(self, args):
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "Task running",
                                "One maintenance or inventory task at a time.")
            return
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self.process.setProgram(str(Path(sys.executable).with_name("python.exe")))
        self.process.setArguments(["-B", *args])
        self.process.readyReadStandardOutput.connect(
            lambda: self.output.appendPlainText(
                bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")))
        self.process.readyReadStandardError.connect(
            lambda: self.output.appendPlainText(
                bytes(self.process.readAllStandardError()).decode("utf-8", "replace")))
        self.process.finished.connect(
            lambda exit_code, status: self.output.appendPlainText(
                f"Task finished: exit code {exit_code}"))
        self.output.appendPlainText("\n> python -B " + " ".join(args))
        self.process.start()

    def _clean(self):
        yes = QMessageBox.question(
            self, "Confirm cache cleanup",
            "Delete only temporary __pycache__ / pytest / lint caches inside the "
            "project? No AFM images, labels, outputs or tracked sources are removed.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if yes == QMessageBox.Yes:
            self._task(("-m", "afm_copilot.maintenance", "clean-safe"))

    def _push(self):
        yes = QMessageBox.question(
            self, "Push existing commits",
            "Push ONLY existing commits on dev/image-wizard to origin?\n"
            "No automatic add/commit, no merge into main, no force push.\n"
            "Push will be blocked if the working tree contains uncommitted changes.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if yes == QMessageBox.Yes:
            self._task(("-m", "afm_copilot.maintenance", "push"))


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AFM Copilot Workstation")
    win = Launcher()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
