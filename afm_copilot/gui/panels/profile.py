"""
The profile panel: drag the line on the image, watch the section update.

This is the thing a conversation cannot do. Positioning a profile is a visual
judgement -- you move it until it crosses the feature the way you want -- and
the plot has to follow immediately.

The step measurement runs on the visible profile, and reports its refusals in
the same words the command line uses.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QVBoxLayout)

from afm_copilot.analysis import measure_step_iso5436
from afm_copilot.gui.panels.base import Panel
from afm_copilot.profile import Profile, extract_profile
from afm_copilot.render import pick_unit

ACCENT = "#1d6b62"
WARN = "#a33a22"


class ProfilePanel(Panel):
    title = "Profile"
    area = "bottom"

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("Average over"))
        self.band = QSpinBox()
        self.band.setRange(1, 128)
        self.band.setValue(16)
        self.band.setSuffix(" rows")
        self.band.setToolTip(
            "Averaging several parallel lines keeps the shape and cuts the "
            "noise -- 16 rows has about a quarter of the scatter of one.")
        self.band.valueChanged.connect(lambda _: self.refresh())
        row.addWidget(self.band)

        self.measure_btn = QPushButton("Measure step")
        self.measure_btn.clicked.connect(self._measure)
        row.addWidget(self.measure_btn)

        self.export_btn = QPushButton("Export .txt")
        self.export_btn.setToolTip(
            "Two-column text in the same format Gwyddion's profile tool "
            "exports.")
        self.export_btn.clicked.connect(self._export)
        row.addWidget(self.export_btn)

        row.addStretch(1)
        layout.addLayout(row)

        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "distance", units="m")
        self.plot.setLabel("left", "height", units="m")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.curve = self.plot.plot(pen=pg.mkPen(ACCENT, width=1.5))
        layout.addWidget(self.plot, 1)

        self.verdict = QLabel("Drag the cyan line on the image to move the "
                              "profile.")
        self.verdict.setWordWrap(True)
        self.verdict.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout.addWidget(self.verdict)

        self._profile: Profile | None = None
        self._line = ((0.0, 0.5), (1.0, 0.5))
        self._levels: list[pg.InfiniteLine] = []

        self.ctx.on_channel_changed(lambda ch, path: self.refresh())

    # ---------------------------------------------------------------- data
    def set_line_pixels(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Called by the viewer as the user drags the line."""
        self._line = ((x0, y0), (x1, y1))
        self.refresh()

    def refresh(self) -> None:
        ch = self.ctx.channel
        if ch is None:
            self.curve.setData([], [])
            return
        try:
            self._profile = extract_profile(
                ch, self._line[0], self._line[1],
                band_px=self.band.value(), fractional=False)
        except ValueError:
            return

        prof = self._profile
        base = float(np.nanmin(ch.data))
        self.curve.setData(prof.distance, prof.height - base)
        self._clear_levels()

    def _clear_levels(self) -> None:
        for line in self._levels:
            self.plot.removeItem(line)
        self._levels.clear()

    # ------------------------------------------------------------ actions
    def _measure(self) -> None:
        if self._profile is None:
            self.verdict.setText("No profile yet -- select a scan first.")
            return

        name = (self.ctx.channel_path.name if self.ctx.channel_path
                else "this scan")
        result = measure_step_iso5436(self._profile, source=name)
        self.verdict.setText(result.explain())
        self.verdict.setStyleSheet(
            "font-family: monospace; font-size: 11px;"
            + ("" if result.ok else f" color: {WARN};"))
        self.ctx.log(result.explain())

        self._clear_levels()
        if result.ok:
            base = float(np.nanmin(self.ctx.channel.data))
            for level in (result.lower_level, result.upper_level):
                line = pg.InfiniteLine(pos=level - base, angle=0,
                                       pen=pg.mkPen(WARN, style=2, width=1))
                self.plot.addItem(line)
                self._levels.append(line)
            factor, unit = pick_unit(abs(result.value))
            self.ctx.log(f"Step: {result.value / factor:.3f} {unit}"
                         + ("  [MARGINAL]" if result.confidence == "marginal"
                            else ""))

    def _export(self) -> None:
        if self._profile is None:
            return
        stem = (self.ctx.channel_path.stem if self.ctx.channel_path
                else "profile")
        default = str(self.ctx.work_dir / f"{stem}_profile.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export profile", default, "Text (*.txt)")
        if not path:
            return
        self._profile.to_text(path)
        self.ctx.log(f"Profile exported to {path}")
        self.verdict.setText(f"Exported to {path}")
