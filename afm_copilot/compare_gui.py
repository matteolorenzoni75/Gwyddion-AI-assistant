"""AFM synoptic comparison: raw / operator corrected / automated, local GUI.

Three independent viewers. Operator verdict is stored privately, not used as
training truth until reviewed. No source scans are ever edited or uploaded.
"""
from __future__ import annotations

import json
import sys
import numpy as np
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
    QSplitter, QSizePolicy,
)

from afm_copilot.gui.viewer import ScanViewer
from afm_copilot.labeler import _load
from afm_copilot.manual_pairs import PRIVATE_ROOT, scan_folder
from afm_copilot.gwy_io import load_height
from afm_copilot.comparison_metrics import shape_comparison

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
        desktop = QApplication.primaryScreen()
        bounds = desktop.availableGeometry() if desktop else None
        if bounds:
            self.resize(min(1500, int(bounds.width() * 0.94)),
                        min(840, int(bounds.height() * 0.90)))
        else:
            self.resize(1280, 760)
        self.setMinimumSize(850, 580)
        self.rows = []
        self.work_dir = Path(tempfile.gettempdir()) / "afm_copilot_compare"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        body = QWidget()
        layout = QVBoxLayout(body)
        top = QHBoxLayout()
        choose = QPushButton("Apri cartella...")
        choose.clicked.connect(self._choose)
        top.addWidget(choose)
        attach = QPushButton("Associa automatico...")
        attach.setToolTip(
            "Seleziona una copia già elaborata in locale per questa scansione. "
            "Nessun dato viene modificato.")
        attach.clicked.connect(self._attach_automated)
        top.addWidget(attach)
        self.generate_button = QPushButton("Genera automatiche")
        self.generate_button.setToolTip(
            "Elabora fino a 16 originali della lista privata con le sole "
            "operazioni Gwyddion ammesse dalla diagnosi. Le immagini restano "
            "da approvare nel confronto sinottico.")
        self.generate_button.clicked.connect(self._generate_auto)
        top.addWidget(self.generate_button)
        self.mask_button = QPushButton("Maschera e correggi...")
        self.mask_button.setToolTip(
            "Regola la soglia in nm, controlla in rosso le zone protette e "
            "applica il fit Gwyddion soltanto dopo conferma.")
        self.mask_button.clicked.connect(self._mask_and_correct)
        top.addWidget(self.mask_button)
        self.auto_process = None
        layout.addLayout(top)
        selection = QHBoxLayout()
        selection.addWidget(QLabel("Scansione"))
        self.select = QComboBox()
        self.select.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.select.currentIndexChanged.connect(self._show)
        selection.addWidget(self.select, 1)
        self.previous_button = QPushButton("◀ Precedente")
        self.previous_button.clicked.connect(self._previous)
        selection.addWidget(self.previous_button)
        self.next_button = QPushButton("Successiva ▶")
        self.next_button.clicked.connect(self._next)
        selection.addWidget(self.next_button)
        self.common_colors = QCheckBox("Scala Z comune")
        self.common_colors.setChecked(True)
        self.common_colors.setToolTip(
            "Usa lo stesso intervallo fisico di altezze, dopo l'offset di "
            "zero di ciascuna immagine. Non cambia i valori Z.")
        self.common_colors.toggled.connect(self._apply_common_scale)
        selection.addWidget(self.common_colors)
        layout.addLayout(selection)

        self.viewer_splitter = QSplitter(Qt.Horizontal)
        self.viewer_splitter.setChildrenCollapsible(False)
        self.viewers = []
        for title in ("ORIGINAL / RAW", "CORRETTA MANUALMENTE", "CORREZIONE AUTOMATICA"):
            column = QVBoxLayout()
            heading = QLabel(title)
            heading.setAlignment(Qt.AlignCenter)
            column.addWidget(heading)
            viewer = ScanViewer()
            viewer.profile_check.setChecked(False)
            column.addWidget(viewer, 1)
            self.viewers.append(viewer)
            holder = QWidget()
            holder.setLayout(column)
            holder.setMinimumWidth(200)
            self.viewer_splitter.addWidget(holder)
        for index in range(3):
            self.viewer_splitter.setStretchFactor(index, 1)
        self.viewer_splitter.setSizes([1, 1, 1])
        layout.addWidget(self.viewer_splitter, 1)
        self.info = QLabel("Choose a folder containing original and corrected versions. "
                           "Matches are candidates until visually verified.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        decision = QHBoxLayout()
        decision.addWidget(QLabel("Valutazione"))
        self.verdict = QComboBox()
        self.verdict.setMaximumWidth(420)
        for label, key in VERDICTS:
            self.verdict.addItem(label, key)
        decision.addWidget(self.verdict, 1)
        save = QPushButton("Conferma e successiva")
        save.setMinimumWidth(150)
        save.clicked.connect(self._validate)
        decision.addWidget(save)
        decision.addStretch(1)
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

    def _previous(self):
        index = self.select.currentIndex()
        if index > 0:
            self.select.setCurrentIndex(index - 1)

    def _next(self):
        index = self.select.currentIndex()
        if 0 <= index < len(self.rows) - 1:
            self.select.setCurrentIndex(index + 1)

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
        self.mask_button.setEnabled(True)
        if code != 0:
            details = bytes(self.auto_process.readAllStandardError()).decode(
                "utf-8", "replace")[-600:]
            QMessageBox.warning(
                self, "Elaborazione non completata",
                f"Exit code {code}. {details or 'Controlla il modulo auto_compare.'}")
            return
        details = bytes(self.auto_process.readAllStandardOutput()).decode(
            "utf-8", "replace")
        previous_index = self.select.currentIndex()
        self._load_private_manifest()
        if 0 <= previous_index < len(self.rows):
            self.select.setCurrentIndex(previous_index)
            self._show(previous_index)
        QMessageBox.information(
            self, "Elaborazione completata",
            "I risultati prodotti sono collegati alla terza colonna e "
            "richiedono la tua validazione.\\n" + details[-900:])

    def _mask_and_correct(self):
        """One scan; approval covers the exact mask shown in the preview."""
        index = self.select.currentIndex()
        if not 0 <= index < len(self.rows):
            return
        if self.auto_process is not None and self.auto_process.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "Operazione attiva",
                                "Termina l'elaborazione precedente.")
            return
        from afm_copilot.mask_review_gui import MaskReviewDialog
        from afm_copilot.masked_compare import save_approved_mask
        channel = self.viewers[0].channel
        if channel is None:
            QMessageBox.warning(self, "Originale non disponibile",
                                "Apri prima la scansione originale.")
            return
        dialog = MaskReviewDialog(channel, self)
        if dialog.exec() != dialog.Accepted or dialog.proposal is None:
            return
        proposal = dialog.proposal
        if not proposal.safe_for_fit:
            return
        try:
            approved = save_approved_mask(
                index, Path(self.rows[index]["original"]),
                proposal.mask, threshold_nm=proposal.threshold_nm,
                mode=dialog.mode.currentData(),
                remove_scars=dialog.remove_scars.isChecked())
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Maschera non salvata", str(error))
            return
        self.auto_process = QProcess(self)
        self.auto_process.setWorkingDirectory(
            str(Path(__file__).resolve().parents[1]))
        python = Path(sys.executable).with_name("python.exe")
        self.auto_process.setProgram(str(python if python.is_file()
                                         else Path(sys.executable)))
        self.auto_process.setArguments([
            "-B", "-m", "afm_copilot.masked_compare",
            "--index", str(index), "--approval", str(approved)])
        self.generate_button.setEnabled(False)
        self.mask_button.setEnabled(False)
        self.info.setText("Fit Gwyddion mascherato in esecuzione...")
        self.auto_process.finished.connect(self._auto_finished)
        self.auto_process.start()

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

    def _apply_common_scale(self, *_):
        loaded = [v for v in self.viewers if v.channel is not None]
        if not loaded:
            return
        if self.common_colors.isChecked():
            # Every viewer shows (Z - local min) / selected display unit.
            # Use one common robust physical span to avoid color deception.
            limits = []
            for viewer in loaded:
                image = np.asarray(viewer.channel.data, dtype=float)
                finite = image[np.isfinite(image)]
                if finite.size:
                    limits.append(float(
                        np.percentile(finite, 99.5) - np.min(finite)))
            span = max(limits, default=1e-9)
            if span <= 0:
                span = 1e-9
            for viewer in loaded:
                viewer.hist.setLevels(0, span / viewer._unit_factor)
        else:
            # Restore the individual robust histogram intervals.
            for viewer in loaded:
                displayed = np.asarray(viewer.image.image, dtype=float)
                finite = displayed[np.isfinite(displayed)]
                if finite.size:
                    lo, hi = np.percentile(finite, (0.5, 99.5))
                    if hi <= lo:
                        hi = lo + 1e-12
                    viewer.hist.setLevels(float(lo), float(hi))

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
        measurements = {}
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
                measurements[key] = channel
                lines.append(
                    f"{key}: {channel.xres}x{channel.yres}, "
                    f"RMS={channel.rms * 1e9:.3g} nm, "
                    f"Z range={channel.z_range * 1e9:.3g} nm")
            except Exception as error:
                viewer.show_channel(None)
                lines.append(
                    f"{key}: import failed ({type(error).__name__})"
                    + (f" — {str(error)[:180]}" if str(error) else ""))
        if "manual" in measurements and "automated" in measurements:
            comparison = shape_comparison(measurements["manual"],
                                          measurements["automated"])
            if comparison["comparable"]:
                lines.append(
                    f"Manuale vs automatico: RMSE profilo = "
                    f"{comparison['shape_rmse_nm']:.2f} nm "
                    "(dopo offset Z; non misura l'accuratezza)")
            else:
                lines.append("Confronto numerico non possibile: " +
                             comparison["reason"])
        self._apply_common_scale()
        self.info.setText("  |  ".join(lines) +
                          "\nLa scala Z comune usa il minimo locale come zero. "
                          "Valuta anche i profili numerici.")
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
