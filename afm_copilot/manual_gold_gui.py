"""Manual gold-set review in the existing workstation; no bulk file copies."""
from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QProgressBar, QLineEdit, QVBoxLayout,
    QWidget, QComboBox)
from afm_copilot.bridge import BridgeConfig
from afm_copilot.gwy_io import load_height
from afm_copilot.labeler import _load
from afm_copilot.manual_gold_set import (discover, latest, record, working_copy,
    export_manifest, sha256, STATE_ROOT)
from afm_copilot.paths import BLIND_INPUT, MANUAL_CORRECTED, PROJECT_ROOT


class GoldWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AFM Copilot - Manual Gold Set")
        self.resize(820, 390)
        self.pool = BLIND_INPUT
        self.files = []
        self.current_hash = None
        body = QWidget()
        layout = QVBoxLayout(body)
        row = QHBoxLayout()
        self.folder = QLabel()
        self.folder.setWordWrap(True)
        row.addWidget(self.folder, 1)
        select = QPushButton("Scegli pool blind")
        select.clicked.connect(self.choose_pool)
        row.addWidget(select)
        layout.addLayout(row)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.selection = QComboBox()
        self.selection.currentIndexChanged.connect(self.show_case)
        layout.addWidget(self.selection)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Note / motivazione della decisione")
        layout.addWidget(self.notes)
        edit = QPushButton("Apri copia di lavoro in Gwyddion")
        edit.clicked.connect(self.open_gwyddion)
        layout.addWidget(edit)
        row = QHBoxLayout()
        for title, decision in (("Importa .gwy corretto", "corrected"),
                                ("Nessuna correzione", "no_change"),
                                ("Non recuperabile", "reject"),
                                ("Rimanda", "deferred")):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, d=decision: self.decide(d))
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        back = QPushButton("Precedente")
        back.clicked.connect(lambda: self.navigate(-1))
        row.addWidget(back)
        forward = QPushButton("Successiva")
        forward.clicked.connect(lambda: self.navigate(1))
        row.addWidget(forward)
        export = QPushButton("Esporta e confronta")
        export.clicked.connect(self.export_review)
        row.addWidget(export)
        layout.addLayout(row)
        layout.addStretch()
        self.setCentralWidget(body)
        self.reload()

    def choose_pool(self):
        folder = QFileDialog.getExistingDirectory(self, "Cartella con scansioni anonimizzate",
                                                   str(self.pool))
        if folder:
            self.pool = Path(folder)
            self.reload()

    def reload(self):
        self.files = discover(self.pool)
        self.folder.setText(str(self.pool))
        self.selection.blockSignals(True)
        self.selection.clear()
        for f in self.files:
            self.selection.addItem(f.name)
        self.selection.blockSignals(False)
        self.update_progress()
        first = next((i for i, p in enumerate(self.files)
                      if (latest(p) or {}).get("decision") in (None, "deferred")), 0)
        self.selection.setCurrentIndex(first if self.files else -1)
        self.show_case(self.selection.currentIndex())

    def update_progress(self):
        completed = sum((latest(p) or {}).get("decision") not in (None, "deferred")
                        for p in self.files)
        self.progress.setRange(0, max(1, len(self.files)))
        self.progress.setValue(completed)
        self.progress.setFormat(f"{completed}/{len(self.files)} review completate")

    def source(self):
        i = self.selection.currentIndex()
        if not 0 <= i < len(self.files):
            raise ValueError("Nessuna scansione blind disponibile")
        return self.files[i]

    def show_case(self, index):
        self.notes.clear()
        if not 0 <= index < len(self.files):
            self.current_hash = None
            self.status.setText("Nessun file anonimo AFM_... nella cartella selezionata.")
            return
        source = self.files[index]
        try:
            self.current_hash = sha256(source)
            state = latest(source)
            self.status.setText(f"{index + 1}/{len(self.files)}: " +
                                (state["decision"] if state else "Da revisionare") +
                                ". Salva la correzione come nuovo file GWY.")
            if state:
                self.notes.setText(state["notes"])
        except (OSError, ValueError) as error:
            self.current_hash = None
            self.status.setText(str(error))

    def navigate(self, step):
        self.selection.setCurrentIndex(max(0, min(len(self.files)-1,
                                                self.selection.currentIndex()+step)))

    def open_gwyddion(self):
        try:
            source = self.source()
            if self.current_hash is None or sha256(source) != self.current_hash:
                raise ValueError("Input changed: reselect the scan")
            root = BridgeConfig().gwyddion_root
            exe = next((p for p in (root / "bin" / "gwyddion.exe", root / "gwyddion.exe")
                        if p.is_file()), None)
            if exe is None:
                raise FileNotFoundError("Gwyddion executable not found")
            draft = working_copy(source)
            MANUAL_CORRECTED.mkdir(parents=True, exist_ok=True)
            subprocess.Popen([str(exe), str(draft)])
            self.status.setText("Gwyddion aperto su una copia. Usa Save As: " +
                                str(MANUAL_CORRECTED / (source.stem + " corrected.gwy")))
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Apertura non riuscita", str(error))

    def decide(self, decision):
        try:
            source = self.source()
            if self.current_hash is None:
                raise ValueError("Input non verificato")
            reference = None
            if decision == "corrected":
                filename, _ = QFileDialog.getOpenFileName(
                    self, "Importa la correzione della scansione corrente",
                    str(MANUAL_CORRECTED / (source.stem + " corrected.gwy")),
                    "Gwyddion (*.gwy)")
                if not filename:
                    return
                reference = Path(filename)
                raw, _ = _load(source, STATE_ROOT / "preview")
                manual = load_height(reference)
                if (raw.data.shape != manual.data.shape or raw.xy_unit != manual.xy_unit
                        or raw.z_unit != manual.z_unit
                        or not math.isclose(raw.xreal, manual.xreal, rel_tol=1e-8)
                        or not math.isclose(raw.yreal, manual.yreal, rel_tol=1e-8)):
                    raise ValueError("Geometria o unita non coincidenti: revisione separata necessaria")
                if QMessageBox.question(self, "Associazione manuale",
                    "Confermi che il GWY appartiene a questa stessa scansione?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                    return
            record(source, decision, reference=reference, notes=self.notes.text(),
                   expected_source_hash=self.current_hash)
            self.update_progress()
            self.show_case(self.selection.currentIndex())
            self.navigate(1)
        except Exception as error:
            QMessageBox.warning(self, "Review non salvata", str(error))

    def export_review(self):
        try:
            summary = export_manifest(self.pool)
            QMessageBox.information(self, "Gold set esportato",
                f"Coppie: {summary['pairs']}; controlli: {summary['controls']}; "
                f"rifiuti: {summary['rejected']}. Nessun training automatico.")
            if summary["pairs"]:
                subprocess.Popen([sys.executable, "-m", "afm_copilot.compare_gui",
                                  "--manifest", summary["path"]], cwd=str(PROJECT_ROOT))
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Export non riuscito", str(error))


def main():
    app = QApplication(sys.argv)
    window = GoldWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
