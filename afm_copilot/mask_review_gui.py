"""Operator-adjustable mask overlay for scientific AFM background levelling."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLabel, QVBoxLayout,
)

from afm_copilot.gui.viewer import ScanViewer
from afm_copilot.mask_refinement import propose_mask, robust_plane


class MaskReviewDialog(QDialog):
    """Red overlay = excluded from fit, NOT deleted/interpolated."""

    def __init__(self, channel, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Maschera Gwyddion — esclusione dal fit")
        self.resize(900, 760)
        self.channel = channel
        self.proposal = None
        layout = QVBoxLayout(self)
        self.viewer = ScanViewer()
        self.viewer.show_channel(channel)
        layout.addWidget(self.viewer, 1)
        self.overlay = pg.ImageItem(axisOrder="row-major")
        self.overlay.setZValue(10)
        self.viewer.plot.addItem(self.overlay)
        self.overlay.setRect(0, 0, channel.xreal, channel.yreal)

        form = QFormLayout()
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.1, 10000.0)
        self.threshold.setDecimals(2)
        self.threshold.setSuffix(" nm")
        self.threshold.setSingleStep(0.5)
        self.estimated_plane = robust_plane(channel.data)
        residual = np.asarray(channel.data, dtype=float) - self.estimated_plane
        span = np.percentile(residual, 90) - np.percentile(residual, 10)
        initial = float(np.clip(0.15 * span * 1e9, 0.1, 10000))
        self.threshold.setValue(initial)
        form.addRow("Soglia dal piano stimato", self.threshold)
        self.mode = QComboBox()
        self.mode.addItem("Rilievi e depressioni", "both")
        self.mode.addItem("Solo rilievi", "raised")
        self.mode.addItem("Solo depressioni", "sunken")
        form.addRow("Feature da escludere", self.mode)
        self.remove_scars = QCheckBox("Rimuovi line scars con Gwyddion (opzionale)")
        self.remove_scars.setChecked(False)
        self.remove_scars.setToolTip(
            "Dopo il fit mascherato, applica Remove Scars. Può intaccare "
            "strutture orizzontali reali: controlla il risultato.")
        form.addRow("Riparazione linee", self.remove_scars)
        layout.addLayout(form)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Conferma maschera e correggi")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.threshold.valueChanged.connect(self._update)
        self.mode.currentIndexChanged.connect(self._update)
        self._update()

    def _update(self, *_):
        try:
            proposal = propose_mask(
                self.channel.data, threshold_nm=self.threshold.value(),
                mode=self.mode.currentData(),
                estimated_plane=self.estimated_plane)
        except ValueError as error:
            self.proposal = None
            self.summary.setText(str(error))
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        self.proposal = proposal
        h, w = proposal.mask.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[proposal.mask] = [250, 35, 76, 110]
        self.overlay.setImage(rgba, autoLevels=False)
        self.overlay.setRect(0, 0, self.channel.xreal, self.channel.yreal)
        self.summary.setText(
            f"Zona protetta: {proposal.masked_fraction:.1%} · "
            f"Minimo background libero per riga: "
            f"{proposal.min_unmasked_row_fraction:.0%}\n"
            f"{proposal.reason}. Il rosso viene ESCLUSO dal fit, "
            "non cancellato.")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(
            proposal.safe_for_fit)
