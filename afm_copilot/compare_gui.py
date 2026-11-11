"""AFM synoptic comparison: raw / operator corrected / automated, local GUI.

Three independent viewers. Operator verdict is stored privately, not used as
training truth until reviewed. No source scans are ever edited or uploaded.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from afm_copilot.gui.viewer import ScanViewer
from afm_copilot.labeler import _load
from afm_copilot.manual_pairs import PRIVATE_ROOT, scan_folder
from afm_copilot.gwy_io import load_height

VERDICTS = (
    ("Manual correction preferred", "manual_preferred"),
    ("Automatic result accepted", "auto_accepted"),
    ("Equivalent / acceptable both", "equivalent"),
    ("Both require revision", "both_reject"),
    ("Undetermined — review later", "needs_review"),
)


class CompareWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AFM Copilot — Synoptic correction review")
        self.resize(1740, 850)
        self.rows = []
        self.work_dir = Path(tempfile.gettempdir()) / "afm_copilot_compare"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        body = QWidget()
        layout = QVBoxLayout(body)
        top = QHBoxLayout()
        choose = QPushButton("Open comparison folder")
        choose.clicked.connect(self._choose)
        top.addWidget(choose)
        self.select = QComboBox()
        self.select.currentIndexChanged.connect(self._show)
        top.addWidget(self.select, 1)
        layout.addLayout(top)
        viewer_row = QHBoxLayout()
        self.viewers = []
        for title in ("ORIGINAL / RAW", "CORRETTA MANUALMENTE", "CORREZIONE AUTOMATICA"):
            column = QVBoxLayout()
            heading = QLabel(title)
            heading.setAlignment(Qt.AlignCenter)
            column.addWidget(heading)
            viewer = ScanViewer()
            column.addWidget(viewer, 1)
            self.viewers.append(viewer)
            holder = QWidget()
            holder.setLayout(column)
            viewer_row.addWidget(holder, 1)
        layout.addLayout(viewer_row, 1)
        self.info = QLabel("Choose a folder containing original and corrected versions. "
                           "Matches are candidates until visually verified.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        decision = QHBoxLayout()
        self.verdict = QComboBox()
        for label, key in VERDICTS:
            self.verdict.addItem(label, key)
        decision.addWidget(QLabel("Operator verdict:"))
        decision.addWidget(self.verdict, 1)
        save = QPushButton("Validate + next")
        save.clicked.connect(self._validate)
        decision.addWidget(save)
        layout.addLayout(decision)
        self.setCentralWidget(body)
        self._load_private_manifest()

    def _load_private_manifest(self):
        candidate_path = PRIVATE_ROOT / "PRIVATE_manual_pair_candidates.json"
        if candidate_path.is_file():
            try:
                data = json.loads(candidate_path.read_text(encoding="utf-8"))
                self._set_rows(data.get("pairs", []))
            except (OSError, ValueError):
                pass

    def _set_rows(self, rows):
        self.rows = list(rows)
        self.select.blockSignals(True)
        self.select.clear()
        for index, row in enumerate(self.rows, 1):
            # Private names displayed only in the local desktop app.
            self.select.addItem(f"{index:03d} — {Path(row['original']).name}")
        self.select.blockSignals(False)
        if self.rows:
            self.select.setCurrentIndex(0)
            self._show(0)
        else:
            self.info.setText("No unambiguous pairs found. Choose the directory "
                              "that contains both the original and the operator-corrected file.")
            for viewer in self.viewers:
                viewer.show_channel(None)

    def _choose(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose original / corrected folder", str(Path.home()))
        if folder:
            result = scan_folder(Path(folder))
            self._set_rows(result["pairs"])
            self.info.setText(
                f"Found {len(result['pairs'])} candidate pairs among "
                f"{result['scanned']} files. No input has been modified.")

    def _channel(self, path):
        if not path:
            return None, {}
        file = Path(path)
        # Operator-corrected Gwyddion files sometimes have names like
        # "sample.ibw corrected with facet level" (no .gwy extension).
        # First try the native Gwyddion reader by file content.
        try:
            ch = load_height(file)
            return ch, {}
        except (OSError, ValueError, TypeError):
            pass
        ch, metrics = _load(file, self.work_dir)
        return ch, metrics

    def _show(self, index):
        if not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        lines = []
        for viewer, key in zip(self.viewers, ("original", "manual", "automated")):
            path = row.get(key)
            if not path:
                viewer.show_channel(None)
                lines.append(f"{key}: not found")
                continue
            try:
                channel, _ = self._channel(path)
                viewer.show_channel(channel)
                lines.append(
                    f"{key}: {channel.xres}x{channel.yres}, "
                    f"RMS={channel.rms * 1e9:.3g} nm, "
                    f"Z range={channel.z_range * 1e9:.3g} nm")
            except Exception as error:
                viewer.show_channel(None)
                lines.append(f"{key}: unreadable ({type(error).__name__})")
        self.info.setText("  |  ".join(lines) +
                          "\nDisplay ranges can differ: compare numerical values, "
                          "not only image colors.")
        self.verdict.setCurrentIndex(4)

    def _validate(self):
        index = self.select.currentIndex()
        if not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        verdict = self.verdict.currentData()
        if verdict == "auto_accepted" and not row.get("automated"):
            QMessageBox.warning(
                self, "No automatic result",
                "There is no automatic result to approve for this pair.")
            return
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "original": row["original"], "manual": row["manual"],
            "automated": row.get("automated"), "verdict": verdict,
            "validation_kind": "operator_visual_review",
            "not_a_training_label": True,
        }
        path = PRIVATE_ROOT / "PRIVATE_correction_verdicts.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.info.setText("Operator verdict SAVED locally. Source images unchanged.")
        if index + 1 < len(self.rows):
            self.select.setCurrentIndex(index + 1)


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AFM Copilot — correction review")
    win = CompareWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
