"""AFM Copilot local scientific workstation — compact, symmetric launcher.

Shows the existing processing, expert labeling, manual comparisons and
private maintenance workflows. Never automatically starts archive scans,
publishes data, deletes originals or changes Git branches.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QStyle,
    QToolButton, QVBoxLayout, QWidget,
)

from afm_copilot.feedback import PROJECT_ROOT


WORKFLOW_ACTIONS = (
    ("Elaborazione AFM", "Pulizia, rescaling e ricette Gwyddion.",
     "Apre la GUI principale per visualizzare topografie, applicare ricette "
     "e controllare le operazioni. Non modifica i file originali in avvio.",
     "afm_copilot.gui", "SP_ComputerIcon"),
    ("Expert Labeler", "Classifica le immagini nel database privato.",
     "Una finestra separata ma integrata nel progetto: conserva le tue "
     "etichette esperte e mostra le immagini ancora da classificare.",
     "afm_copilot.labeler", "SP_FileDialogDetailedView"),
    ("Confronto sinottico", "Originale · manuale · automatico.",
     "Apre tre visualizzatori per confrontare topografia, RMS e range Z. "
     "Puoi approvare o rifiutare la correzione: il verdetto resta locale.",
     "afm_copilot.compare_gui", "SP_FileDialogContentsView"),
    ("Cerca correzioni manuali", "Trova le tue precedenti immagini corrette.",
     "Cerca nomi come 'corrected' e abbina originali e correzioni. "
     "Le corrispondenze non sono ancora verificate pixel per pixel.",
     ("-m", "afm_copilot.manual_pairs"), "SP_FileDialogInfoView"),
)
MAINTENANCE_ACTIONS = (
    ("Anteprima archivio", "Inventario AFM ricorsivo, nessuno spostamento.",
     "Calcola i checksum dei file nell'archivio All AFM Data. "
     "Su archivi molto grandi può richiedere tempo: non avviarlo due volte.",
     ("-m", "afm_copilot.archive_organizer"), "SP_DirIcon"),
    ("Stato Git", "Controlla branch e modifiche locali.",
     "Mostra lo stato del repository: nessuna modifica ai file, "
     "nessun upload e nessun commit automatico.",
     ("-m", "afm_copilot.maintenance", "status"), "SP_DriveHDIcon"),
    ("Anteprima pulizia", "Mostra solo le cache eliminabili.",
     "Individua cache Python/pytest e simili. "
     "Non tocca scansioni, database, output o documenti scientifici.",
     ("-m", "afm_copilot.maintenance", "clean-preview"), "SP_TrashIcon"),
    ("Pulizia cache", "Rimuove soltanto cache temporanee note.",
     "Richiede conferma. Non elimina immagini AFM, etichette, "
     "file tracciati o directory dell'archivio.",
     "clean", "SP_DialogApplyButton"),
    ("Push Git", "Pubblica i commit già approvati sul branch dev.",
     "Richiede conferma e una working tree pulita. Non esegue git add, "
     "non crea commit, non forza push e non modifica main.",
     "push", "SP_ArrowUp"),
)


class Launcher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AFM Copilot — Local workstation")
        self.resize(1010, 820)
        self.setMinimumSize(760, 600)
        self.process = None
        self.action_buttons = {}
        self._build()

    def _build(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 15)
        layout.setSpacing(12)

        heading = QLabel("AFM Copilot")
        heading.setObjectName("workstationTitle")
        layout.addWidget(heading)
        subtitle = QLabel(
            "Scientific workstation   •   Topografia prima   •   "
            "Multicanale   •   100% locale")
        subtitle.setObjectName("workstationSubtitle")
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        main = QVBoxLayout(body)
        main.setContentsMargins(0, 4, 0, 2)
        main.setSpacing(16)

        main.addWidget(self._section_title(
            "ANALISI E VALIDAZIONE",
            "Apri le funzioni scientifiche o recupera correzioni già effettuate"))
        actions = QGridLayout()
        actions.setHorizontalSpacing(12)
        actions.setVerticalSpacing(12)
        for i, action in enumerate(WORKFLOW_ACTIONS):
            title, brief, detail, target, icon_name = action
            card = self._card(title, brief, detail, target, icon_name)
            actions.addWidget(card, i // 2, i % 2)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        main.addLayout(actions)

        main.addWidget(self._section_title(
            "ARCHIVIO E MANUTENZIONE",
            "Funzioni di diagnostica e gestione con protezioni sui dati"))
        maintenance = QGridLayout()
        maintenance.setHorizontalSpacing(12)
        maintenance.setVerticalSpacing(12)
        for i, action in enumerate(MAINTENANCE_ACTIONS):
            title, brief, detail, target, icon_name = action
            card = self._card(title, brief, detail, target, icon_name)
            maintenance.addWidget(card, i // 2, i % 2)
        maintenance.setColumnStretch(0, 1)
        maintenance.setColumnStretch(1, 1)
        main.addLayout(maintenance)
        main.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        log_header = QHBoxLayout()
        log_header.addWidget(self._section_title(
            "ATTIVITÀ LOCALI", "Risultati delle operazioni e diagnostica"))
        log_header.addStretch(1)
        clear_log = QPushButton("Svuota registro a schermo")
        clear_log.setObjectName("smallButton")
        clear_log.clicked.connect(self.output_clear)
        log_header.addWidget(clear_log)
        layout.addLayout(log_header)
        self.output = QPlainTextEdit()
        self.output.setObjectName("activityLog")
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(1500)
        self.output.setPlaceholderText(
            "Nessuna attività. Le operazioni locali compariranno qui.")
        self.output.setFixedHeight(135)
        layout.addWidget(self.output)

        self.setCentralWidget(root)
        self._style()

    def _section_title(self, title, subtitle):
        holder = QWidget()
        inner = QVBoxLayout(holder)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(2)
        name = QLabel(title)
        name.setObjectName("sectionLabel")
        inner.addWidget(name)
        desc = QLabel(subtitle)
        desc.setObjectName("sectionSubtitle")
        desc.setWordWrap(True)
        inner.addWidget(desc)
        return holder

    def _card(self, title, brief, detail, target, icon_name):
        frame = QFrame()
        frame.setObjectName("actionCard")
        frame.setMinimumWidth(275)
        block = QVBoxLayout(frame)
        block.setContentsMargins(15, 12, 15, 12)
        block.setSpacing(7)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        symbol = QLabel()
        symbol.setObjectName("cardIcon")
        kind = getattr(QStyle, icon_name, QStyle.SP_FileIcon)
        pix = self.style().standardIcon(kind).pixmap(21, 21)
        symbol.setPixmap(pix)
        heading.addWidget(symbol)
        label = QLabel(title)
        label.setObjectName("cardTitle")
        label.setWordWrap(True)
        heading.addWidget(label, 1)

        help_button = QToolButton()
        help_button.setObjectName("helpButton")
        help_button.setText("?")
        help_button.setToolTip("Mostra / nascondi dettagli")
        help_button.setCheckable(True)
        help_button.setAccessibleName("Dettagli: " + title)
        heading.addWidget(help_button)
        block.addLayout(heading)

        description = QLabel(brief)
        description.setObjectName("cardDescription")
        description.setWordWrap(True)
        block.addWidget(description)

        explanation = QLabel(detail)
        explanation.setObjectName("cardExplanation")
        explanation.setWordWrap(True)
        explanation.setVisible(False)
        help_button.toggled.connect(explanation.setVisible)
        block.addWidget(explanation)

        button = QPushButton("Apri" if isinstance(target, str) and target not in ("clean", "push")
                             else "Esegui")
        button.setObjectName("cardAction")
        button.setMinimumHeight(32)
        button.clicked.connect(
            lambda _checked=False, t=target: self._dispatch(t))
        block.addWidget(button)
        self.action_buttons[title] = button
        return frame

    def _dispatch(self, target):
        if target == "clean":
            self._clean()
        elif target == "push":
            self._push()
        elif isinstance(target, tuple):
            self._task(target)
        else:
            self._launch(target)

    def _style(self):
        self.setStyleSheet("""
            QMainWindow { background: #f4f7fa; color: #203246; }
            QLabel#workstationTitle {
                color: #143b54; font-size: 27px; font-weight: 700;
            }
            QLabel#workstationSubtitle {
                color: #54677a; font-size: 12px;
            }
            QLabel#sectionLabel {
                color: #226d84; font-size: 11px;
                font-weight: 700; letter-spacing: 1px;
            }
            QLabel#sectionSubtitle {
                color: #6a7a87; font-size: 11px;
            }
            QFrame#actionCard {
                background: #ffffff; border: 1px solid #dce5ea;
                border-radius: 10px;
            }
            QLabel#cardIcon, QLabel#cardTitle,
            QLabel#cardDescription, QLabel#cardExplanation {
                background: transparent; border: none;
            }
            QLabel#cardTitle {
                color: #18394d; font-size: 14px; font-weight: 600;
            }
            QLabel#cardDescription {
                color: #566878; font-size: 11px;
            }
            QLabel#cardExplanation {
                color: #35596b; background: #edf5f8;
                border-radius: 5px; padding: 7px; font-size: 11px;
            }
            QToolButton#helpButton {
                border: 1px solid #c5d8e1; color: #27738b;
                border-radius: 12px; min-width: 24px;
                min-height: 24px; font-weight: 700; background: #f5fafc;
            }
            QToolButton#helpButton:checked { background: #dceff5; }
            QPushButton#cardAction {
                background: #1f7388; border: none; color: white;
                border-radius: 6px; padding: 5px 12px; font-weight: 600;
            }
            QPushButton#cardAction:hover { background: #185b70; }
            QPushButton#cardAction:pressed { background: #124758; }
            QPushButton#smallButton {
                color: #365a70; background: transparent;
                border: 1px solid #ccd9e1; border-radius: 5px;
                padding: 5px 8px;
            }
            QPlainTextEdit#activityLog {
                background: #182a39; color: #d6e5ec;
                border: 1px solid #334d60; border-radius: 8px;
                font-family: Consolas; font-size: 11px;
            }
        """)

    def output_clear(self):
        self.output.clear()

    def _launch(self, module):
        executable = Path(sys.executable)
        if executable.name.lower() == "python.exe":
            alternative = executable.with_name("pythonw.exe")
            if alternative.exists():
                executable = alternative
        try:
            subprocess.Popen(
                [str(executable), "-m", module],
                cwd=str(PROJECT_ROOT), close_fds=True)
        except OSError as error:
            QMessageBox.warning(self, "Avvio non riuscito", str(error))
            return
        self.output.appendPlainText("Avviato: " + module)

    def _task(self, args):
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            QMessageBox.warning(
                self, "Operazione in corso",
                "È già attiva un'operazione locale. Attendi che termini.")
            return
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        executable = Path(sys.executable)
        console = executable.with_name("python.exe")
        self.process.setProgram(str(console if console.exists() else executable))
        self.process.setArguments(["-B", *args])
        self.process.readyReadStandardOutput.connect(
            lambda: self.output.appendPlainText(
                bytes(self.process.readAllStandardOutput()).decode(
                    "utf-8", "replace").rstrip()))
        self.process.readyReadStandardError.connect(
            lambda: self.output.appendPlainText(
                bytes(self.process.readAllStandardError()).decode(
                    "utf-8", "replace").rstrip()))
        self.process.finished.connect(
            lambda exit_code, _status: self.output.appendPlainText(
                f"Operazione terminata (codice {exit_code})."))
        self.output.appendPlainText("\n> python -B " + " ".join(args))
        self.process.start()

    def _clean(self):
        answer = QMessageBox.question(
            self, "Conferma pulizia delle cache",
            "Rimuovere soltanto __pycache__, cache pytest/lint nel progetto?\n"
            "Immagini AFM, classificazioni, risultati e file Git tracciati "
            "non saranno eliminati.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._task(("-m", "afm_copilot.maintenance", "clean-safe"))

    def _push(self):
        answer = QMessageBox.question(
            self, "Conferma push Git",
            "Pubblicare soltanto i commit già presenti su dev/image-wizard?\n"
            "Nessun git add/commit automatico, nessun merge su main, "
            "nessun force push.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._task(("-m", "afm_copilot.maintenance", "push"))


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AFM Copilot Workstation")
    win = Launcher()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
