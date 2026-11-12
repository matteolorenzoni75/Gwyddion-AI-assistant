"""AFM expert labeling workstation: python -m afm_copilot.labeler

One image at a time, expanding local collections, persistent private SQLite
labels, and explicit specimen-level train/validation/holdout roles.
There is no training, no auto-classification and no source modification.
"""
from __future__ import annotations

import hashlib
import math
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from afm_copilot.bridge import BridgeError, GwyBridge
from afm_copilot.gui.viewer import ScanViewer
from afm_copilot.gui.workers import TaskRunner
from afm_copilot.gwy_io import load_height
from afm_copilot.features import measure as measure_features
from afm_copilot.paths import HISTORICAL_RAW
from afm_copilot.labeling import (ARTIFACTS, DEFAULT_DB, FAMILIES, QUALITIES,
                                 ROLES, counts, get_scans, register_folder,
                                 save_label)

DEFAULT_FOLDER = HISTORICAL_RAW

FAMILY_LABELS = {
    "unclassified": "Not classified",
    "granular_continuous": "Continuous granular film",
    "isolated_objects": "Isolated particles / islands",
    "terraces": "Terraces / steps / plateaus",
    "pores": "Pores / pits",
    "fibres": "Fibres / filaments",
    "periodic": "Periodic / lattice / grating",
    "flat_smooth": "Smooth / flat",
    "rough_irregular": "Rough / irregular",
    "mixed": "Mixed morphology",
    "uncertain": "Uncertain / cannot determine",
}
ARTIFACT_LABELS = {
    "tilt": "Tilt", "bow": "Curvature / bow", "row_banding": "Row banding",
    "line_scars": "Scan-line scar", "spikes": "Spikes",
    "periodic_noise": "Periodic noise", "drift": "Drift",
    "feedback": "Feedback / parachuting", "double_tip": "Double tip",
    "charging": "Charging", "other": "Other",
}


def _load(path: Path, work_dir: Path):
    """Import raw scans into unique temporary directories and measure features."""
    if path.suffix.lower() == ".gwy":
        target = path
    else:
        # Derived destination is unique per path; raw inputs remain read-only.
        identity = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20]
        into = work_dir / identity
        target = into / (path.stem + ".gwy")
        if not target.is_file():
            result = GwyBridge().convert_raw([path], into)
            records = result.get("results", [])
            ok = [row for row in records if row.get("ok")]
            if not ok:
                raise BridgeError(records[0].get("error", "Import failed")
                                  if records else "No result from Gwyddion")
            target = Path(ok[0]["gwy"])
    channel = load_height(target)
    features = {
        "xres": channel.xres, "yres": channel.yres,
        "xreal_m": channel.xreal, "yreal_m": channel.yreal,
        "rms_raw_m": channel.rms, "z_range_m": channel.z_range,
    }
    # Numerical descriptors are evidence, not automatic morphology labels.
    try:
        measured = measure_features(channel).as_dict()
        for key, value in measured.items():
            if isinstance(value, (int, float)):
                number = float(value)
                features[key] = number if math.isfinite(number) else None
    except Exception:
        # Never hide a readable topography just because a nonessential
        # descriptor failed on an unusual instrument export.
        features["feature_extraction_incomplete"] = True
    return channel, features


class LabelerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AFM Copilot — Expert labeling")
        self.resize(1560, 940)
        self.runner = TaskRunner(max_threads=2)
        self.work_dir = Path(tempfile.gettempdir()) / "afm_copilot_labeling"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.rows = []
        self.position = -1
        self.pending = False
        self.current_metrics = {}
        self._form_baseline = None
        self._build()
        self._refresh()
        if self.rows:
            # Opening an existing label database must display a scan immediately,
            # preferably the first not yet labeled; don't leave the viewer blank.
            first_unlabeled = next(
                (i for i, row in enumerate(self.rows)
                 if row.get("family") is None), 0)
            self._show(first_unlabeled)
        elif DEFAULT_FOLDER.is_dir():
            self._add_folder(DEFAULT_FOLDER)

    def _build(self):
        central = QWidget()
        whole = QVBoxLayout(central)
        toolbar = QHBoxLayout()
        add = QPushButton("Add folder (recursive)")
        add.clicked.connect(self._choose_folder)
        toolbar.addWidget(add)
        self.counter = QLabel("0/0")
        toolbar.addWidget(self.counter)
        toolbar.addStretch(1)
        self.jump_btn = QPushButton("Next unlabelled")
        self.jump_btn.clicked.connect(self._next_unlabeled)
        toolbar.addWidget(self.jump_btn)
        whole.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        self.viewer = ScanViewer()
        splitter.addWidget(self.viewer)

        form_widget = QWidget()
        form_box = QVBoxLayout(form_widget)
        form_box.setSpacing(9)
        self.scan_label = QLabel("No scan selected")
        self.scan_label.setWordWrap(True)
        self.scan_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form_box.addWidget(self.scan_label)

        form = QFormLayout()
        self.family = QComboBox()
        for item in FAMILIES:
            self.family.addItem(FAMILY_LABELS.get(item, item), item)
        form.addRow("Morphology", self.family)
        self.quality = QComboBox()
        for item in QUALITIES:
            self.quality.addItem(item.title(), item)
        form.addRow("Image quality", self.quality)
        self.confidence = QComboBox()
        for n in range(1, 6):
            self.confidence.addItem(f"{n}/5", n)
        self.confidence.setCurrentIndex(2)
        form.addRow("Confidence", self.confidence)
        self.group = QLineEdit()
        self.group.setPlaceholderText("Same specimen / acquisition session ID")
        form.addRow("Specimen / session", self.group)
        self.role = QComboBox()
        for item in ROLES:
            self.role.addItem(item.title(), item)
        form.addRow("Dataset partition", self.role)
        form_box.addLayout(form)

        form_box.addWidget(QLabel("Acquisition / image artifacts (select all that apply)"))
        self.flags = {}
        for key in ARTIFACTS:
            box = QCheckBox(ARTIFACT_LABELS.get(key, key))
            self.flags[key] = box
            form_box.addWidget(box)

        form_box.addWidget(QLabel("Operator observations / morphology details"))
        self.notes = QTextEdit()
        self.notes.setPlaceholderText(
            "E.g. grain shape, islands, steps, polymer texture, "
            "substrate visibility, expected real features, "
            "which signal is unreliable, suggested handling.")
        self.notes.setMinimumHeight(115)
        form_box.addWidget(self.notes)

        self.status = QLabel("Labels are stored privately, outside GitHub. "
                             "No image is modified.")
        self.status.setWordWrap(True)
        form_box.addWidget(self.status)

        actions = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Previous")
        self.prev_btn.clicked.connect(self._previous)
        actions.addWidget(self.prev_btn)
        self.save_btn = QPushButton("Save label")
        self.save_btn.clicked.connect(lambda: self._save(False))
        actions.addWidget(self.save_btn)
        self.save_next_btn = QPushButton("Save + next ▶")
        self.save_next_btn.clicked.connect(lambda: self._save(True))
        actions.addWidget(self.save_next_btn)
        next_btn = QPushButton("Skip ▶")
        next_btn.clicked.connect(self._next)
        actions.addWidget(next_btn)
        form_box.addLayout(actions)
        form_box.addWidget(QLabel(
            "IMPORTANT: Skip does NOT save. Use Save + next to retain labels."))
        form_box.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        scroll.setMinimumWidth(390)
        splitter.addWidget(scroll)
        splitter.setSizes([1050, 460])
        whole.addWidget(splitter, 1)
        self.setCentralWidget(central)

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Add AFM images recursively", str(DEFAULT_FOLDER))
        if folder:
            self._add_folder(Path(folder))

    def _add_folder(self, folder: Path):
        if self.pending:
            return
        try:
            result = register_folder(folder)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self._refresh()
        self.status.setText(
            f"Folder scanned: {result['found']} scans; {result['added']} new. "
            "Existing labels retained.")
        if self.position < 0 and self.rows:
            self._show(0)

    def _refresh(self):
        previous_id = (self.rows[self.position]["scan_id"]
                       if 0 <= self.position < len(self.rows) else None)
        self.rows = get_scans()
        if previous_id is not None:
            self.position = next(
                (i for i, r in enumerate(self.rows) if r["scan_id"] == previous_id), -1)
        stats = counts()
        self.counter.setText(
            f"{stats['labeled']}/{stats['total']} labelled "
            f"(train {stats['roles']['train']}, validation "
            f"{stats['roles']['validation']}, holdout {stats['roles']['holdout']})")

    def _form_values(self):
        return (
            self.family.currentData(), self.quality.currentData(),
            self.confidence.currentData(), self.group.text(),
            self.role.currentData(), tuple(sorted(
                key for key, box in self.flags.items() if box.isChecked())),
            self.notes.toPlainText(),
        )

    def _confirm_discard(self):
        if self._form_baseline is None or self._form_values() == self._form_baseline:
            return True
        answer = QMessageBox.question(
            self, "Unsaved AFM classification",
            "The current image has unsaved labeling changes. "
            "Discard them and move on?\n\n"
            "Choose No, then Save + next to keep the classification.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _show(self, index):
        if self.pending or not 0 <= index < len(self.rows):
            return
        if self.position != index and not self._confirm_discard():
            return
        self.position = index
        entry = self.rows[index]
        path = Path(entry["path"])
        self.scan_label.setText(
            f"Image {index + 1}/{len(self.rows)} — #{entry['scan_id']}\n"
            f"{path.name}\n{path.parent}")
        for widget, name, fallback in (
            (self.family, "family", "unclassified"),
            (self.quality, "quality", "unknown"),
            (self.role, "dataset_role", "unassigned"),
        ):
            value = entry.get(name) or fallback
            widget.setCurrentIndex(max(0, widget.findData(value)))
        self.confidence.setCurrentIndex(max(0, (entry.get("confidence") or 3) - 1))
        self.group.setText(entry.get("sample_group") or "")
        for key, box in self.flags.items():
            box.setChecked(key in entry["artifacts"])
        self.notes.setPlainText(entry.get("notes") or "")
        self._form_baseline = self._form_values()
        self.pending = True
        self.current_metrics = {}
        self.status.setText("Loading raw scan and measuring descriptors (read-only)...")
        self.runner.submit(
            "Load AFM topography", _load, path, self.work_dir,
            on_result=lambda ch, scan_id=entry["scan_id"]: self._loaded(ch, scan_id),
            on_failed=lambda _desc, error: self._failed(error),
        )

    def _loaded(self, result, scan_id):
        if self.position < 0 or self.rows[self.position]["scan_id"] != scan_id:
            return
        channel, metrics = result
        self.pending = False
        self.current_metrics = metrics
        self.viewer.show_channel(channel)
        self.status.setText(
            f"Loaded {channel.xres}×{channel.yres} px; "
            f"{channel.xreal * 1e6:.3g} × {channel.yreal * 1e6:.3g} µm. "
            "Classify visible morphology, not the filename.")
        if self.rows[self.position].get("family") is None:
            # Default to the first unlabeled entry, not a recommended model label.
            self.family.setCurrentIndex(0)

    def _failed(self, error):
        self.pending = False
        self.current_metrics = {}
        self.viewer.show_channel(None)
        self.status.setText(f"Image could not be loaded: {error}. "
                            "You can skip it and continue the batch.")

    def _save(self, advance):
        if self.pending or not 0 <= self.position < len(self.rows):
            return
        entry = self.rows[self.position]
        try:
            save_label(
                entry["scan_id"], family=self.family.currentData(),
                artifacts=[key for key, box in self.flags.items() if box.isChecked()],
                quality=self.quality.currentData(),
                confidence=self.confidence.currentData(),
                sample_group=self.group.text(),
                dataset_role=self.role.currentData(),
                notes=self.notes.toPlainText(),
                metrics=self.current_metrics,
            )
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Label not saved", str(exc))
            return
        self._refresh()
        self._form_baseline = self._form_values()
        self.status.setText("Label SAVED in the private database. Original raw image unchanged.")
        if advance:
            self._next()

    def _previous(self):
        self._show(self.position - 1)

    def _next(self):
        self._show(self.position + 1)

    def _next_unlabeled(self):
        if not self.rows:
            return
        starts = list(range(self.position + 1, len(self.rows))) + list(range(0, self.position + 1))
        next_position = next(
            (i for i in starts if self.rows[i].get("family") is None), None)
        if next_position is None:
            self.status.setText("All imported images have been reviewed.")
        else:
            self._show(next_position)

    def closeEvent(self, event):
        if self.runner.busy:
            QMessageBox.information(
                self, "Import in progress",
                "Finish loading the current image before closing.")
            event.ignore()
            return
        if not self._confirm_discard():
            event.ignore()
            return
        event.accept()


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AFM Copilot Expert Labeler")
    win = LabelerWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
