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

from PySide6.QtCore import Qt, QProcess
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
        attach = QPushButton("Associa risultato automatico...")
        attach.setToolTip(
            "Seleziona una copia già elaborata in locale per questa scansione. "
            "Nessun dato viene modificato.")
        attach.clicked.connect(self._attach_automated)
        top.addWidget(attach)
        self.generate_button = QPushButton("Genera correzioni AFM Copilot")
        self.generate_button.setToolTip(
            "Elabora fino a 16 originali della lista privata con le sole "
            "operazioni Gwyddion ammesse dalla diagnosi. Le immagini restano "
            "da approvare nel confronto sinottico.")
        self.generate_button.clicked.connect(self._generate_auto)
        top.addWidget(self.generate_button)
        self.auto_process = None
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

    def _generate_auto(self):
        """Run the limited local comparison job without blocking the GUI."""
        from afm_copilot.manual_pairs import PRIVATE_ROOT
        manifest = PRIVATE_ROOT / "PRIVATE_manual_pair_candidates.json"
        if not manifest.is_file():
            QMessageBox.warning(
                self, "Nessuna coppia",
                "Esegui prima 'Cerca correzioni manuali' dal launcher.")
            return
        if self.auto_process is not None and self.auto_process.state() != QProcess.NotRunning:
            QMessageBox.information(
                self, "Elaborazione in corso", "Il batch locale è già attivo.")
            return
        answer = QMessageBox.question(
            self, "Genera correzioni automatiche",
            "Elaborare gli originali delle coppie manuali note con le sole "
            "operazioni ammesse dalla diagnosi?\\n"
            "I risultati saranno salvati separatamente, mai approvati "
            "automaticamente. I casi dubbi resteranno sospesi.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.auto_process = QProcess(self)
        self.auto_process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        python = Path(sys.executable).with_name("python.exe")
        self.auto_process.setProgram(str(python if python.is_file()
                                         else Path(sys.executable)))
        self.auto_process.setArguments([
            "-B", "-m", "afm_copilot.auto_compare",
            "--confirm", "RUN_8_CANDIDATES"])
        self.generate_button.setEnabled(False)
        self.info.setText("Elaborazione Gwyddion avviata sulle coppie note...")
        self.auto_process.finished.connect(self._auto_finished)
        self.auto_process.start()

    def _auto_finished(self, code, _status):
        self.generate_button.setEnabled(True)
        if code != 0:
            details = bytes(self.auto_process.readAllStandardError()).decode(
                "utf-8", "replace")[-600:]
            QMessageBox.warning(
                self, "Elaborazione non completata",
                f"Exit code {code}. {details or 'Controlla il modulo auto_compare.'}")
            return
        details = bytes(self.auto_process.readAllStandardOutput()).decode(
            "utf-8", "replace")
        self._load_private_manifest()
        QMessageBox.information(
            self, "Elaborazione completata",
            "I risultati prodotti sono collegati alla terza colonna e "
            "richiedono la tua validazione.\\n" + details[-900:])

    def _attach_automated(self):
        """Manually associate an existing processed file after operator review."""
        index = self.select.currentIndex()
        if not 0 <= index < len(self.rows):
            return
        selected, _ = QFileDialog.getOpenFileName(
            self, "Scegli risultato elaborato da AFM Copilot",
            str(Path(self.rows[index]["original"]).parent),
            "Gwyddion (*.gwy);;AFM images (*.ibw *.tif *.tiff *.spm);;All files (*)")
        if not selected:
            return
        path = Path(selected)
        if path.resolve() in {
            Path(self.rows[index][name]).resolve()
            for name in ("original", "manual")
            if self.rows[index].get(name)
        }:
            QMessageBox.warning(
                self, "File non valido",
                "Seleziona un file elaborato distinto da originale e manuale.")
            return
        try:
            self._channel(path)
        except Exception as error:
            QMessageBox.warning(
                self, "Risultato non leggibile",
                f"Il file scelto non è leggibile: {type(error).__name__}: {str(error)[:150]}")
            return
        self.rows[index]["automated"] = str(path)
        self._save_private_pairs()
        self._show(index)

    def _save_private_pairs(self):
        from afm_copilot.manual_pairs import save_private
        save_private({
            "schema_version": 1,
            "pairs": self.rows,
            "source": "operator_confirmed_local_comparison_associations",
            "image_contents_modified": False,
        })

    def _channel(self, path, *, operator_corrected=False):
        """Route raw instrument files through the Gwyddion import bridge.

        Corrected files may be Gwyddion containers without a .gwy suffix.
        Never pass a normal .ibw/.tiff to the gwyfile parser by default:
        gwyfile can raise AssertionError on their non-GWY header.
        """
        if not path:
            return None, {}
        file = Path(path)
        if not file.is_file():
            raise FileNotFoundError("Expected local image is no longer available")
        if file.suffix.lower() == ".gwy":
            return load_height(file), {}
        if operator_corrected:
            try:
                return load_height(file), {}
            except (OSError, ValueError, TypeError, AssertionError):
                # An operator may instead have saved an instrument-format
                # image with a 'corrected' suffix. Let Gwyddion attempt import.
                pass
        return _load(file, self.work_dir)

    def _status_for(self, row, key):
        path = row.get(key)
        if not path:
            return ("Automatic output not yet associated"
                    if key == "automated" else "Not associated")
        if not Path(path).is_file():
            return "File does not exist at the recorded path"
        return "File present"


    def _show(self, index):
        if not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        lines = []
        for viewer, key in zip(self.viewers, ("original", "manual", "automated")):
            path = row.get(key)
            if not path:
                viewer.show_channel(None)
                lines.append(f"{key}: {self._status_for(row, key)}")
                continue
            try:
                channel, _ = self._channel(
                    path, operator_corrected=(key == "manual"))
                viewer.show_channel(channel)
                lines.append(
                    f"{key}: {channel.xres}x{channel.yres}, "
                    f"RMS={channel.rms * 1e9:.3g} nm, "
                    f"Z range={channel.z_range * 1e9:.3g} nm")
            except Exception as error:
                viewer.show_channel(None)
                lines.append(
                    f"{key}: import failed ({type(error).__name__})"
                    + (f" — {str(error)[:180]}" if str(error) else ""))
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
