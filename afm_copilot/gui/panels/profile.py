"""
The profile panel: drag the line on the image, watch the section update.

This is the thing a conversation cannot do. Positioning a profile is a visual
judgement -- you move it until it crosses the feature the way you want -- and
the plot has to follow immediately.

There are two ways to measure a step here, and the difference matters:

  Automatic  The height histogram of the whole profile is split into two
             levels, and the distance between their medians is the step. Fast,
             objective, and it refuses when the profile does not actually have
             two levels. It uses everything, so a second feature in the same
             profile will pull the answer.

  Manual     You drag two shaded regions onto the stretches you want compared,
             and the step is the difference of their means. This is what
             measuring with cursors means, and it is the right choice when the
             profile crosses several features and you want one particular step.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QSpinBox, QVBoxLayout)

from afm_copilot.analysis import measure_step_between, measure_step_iso5436
from afm_copilot.gui.panels.base import Panel
from afm_copilot.profile import Profile, extract_profile
from afm_copilot.render import pick_unit

ACCENT = "#1d6b62"
WARN = "#a33a22"
LOWER_FILL = (31, 111, 98, 55)     # the region you call the lower surface
UPPER_FILL = (163, 58, 34, 55)     # and the upper one

AUTOMATIC = "Automatic - find the two levels"
MANUAL = "Manual - drag two regions"


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

        row.addSpacing(12)
        row.addWidget(QLabel("Measure"))
        self.mode = QComboBox()
        self.mode.addItems([AUTOMATIC, MANUAL])
        self.mode.setToolTip(
            "Automatic splits the profile's height histogram into two levels.\n"
            "Manual compares two regions you place yourself -- use it when the "
            "profile crosses more than one feature.")
        self.mode.currentTextChanged.connect(self._mode_changed)
        row.addWidget(self.mode)

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
        self.verdict.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.verdict.setStyleSheet("font-family: Consolas, monospace; "
                                   "font-size: 11px;")
        layout.addWidget(self.verdict)

        self._profile: Profile | None = None
        self._line = ((0.0, 0.5), (1.0, 0.5))
        self._markers: list[pg.GraphicsObject] = []

        # The two cursor regions. Created once and shown only in manual mode,
        # so their position survives switching back and forth.
        self.region_lower = pg.LinearRegionItem(
            values=(0.0, 1.0), brush=pg.mkBrush(*LOWER_FILL),
            pen=pg.mkPen(ACCENT, width=1))
        self.region_upper = pg.LinearRegionItem(
            values=(0.0, 1.0), brush=pg.mkBrush(*UPPER_FILL),
            pen=pg.mkPen(WARN, width=1))
        for region in (self.region_lower, self.region_upper):
            region.setZValue(-10)
            region.sigRegionChanged.connect(self._regions_moved)

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
        heights = prof.height - base
        self.curve.setData(prof.distance, heights)
        self._clear_markers()
        if self.mode.currentText() == MANUAL:
            self._place_regions(prof)
        self._frame(prof, heights)

    def _frame(self, profile: Profile, heights: np.ndarray) -> None:
        """
        Fit the view to the data.

        Set explicitly rather than left to autoRange: the region cursors and
        the level lines are infinite in one direction, and letting them into
        the automatic range pushed the view to millimetres while the profile
        spans nanometres -- the curve vanished off the top of the plot.
        """
        finite = heights[np.isfinite(heights)]
        if finite.size == 0:
            return
        lo, hi = float(finite.min()), float(finite.max())
        pad = (hi - lo) * 0.08 or 1e-12
        self.plot.getViewBox().setRange(
            xRange=(0.0, float(profile.length)),
            yRange=(lo - pad, hi + pad), padding=0)

    # ------------------------------------------------------------- cursors
    def _mode_changed(self, text: str) -> None:
        manual = text == MANUAL
        for region in (self.region_lower, self.region_upper):
            if manual and region.scene() is None:
                self.plot.addItem(region, ignoreBounds=True)
            elif not manual and region.scene() is not None:
                self.plot.removeItem(region)
        self._clear_markers()
        if manual and self._profile is not None:
            self._place_regions(self._profile)
            self.verdict.setText(
                "Drag the two shaded regions onto the surfaces you want "
                "compared, then press Measure step.\n"
                "Green is the lower surface, red the upper one.")
        else:
            self.verdict.setText(
                "The whole profile is used: its heights are split into two "
                "levels and the step is the distance between them.")

    def _place_regions(self, profile: Profile) -> None:
        """
        Put the cursors somewhere useful to start from.

        Seeded from the automatic two-level split, so the regions land on the
        actual plateaux rather than on fixed fractions of the profile -- on a
        scan whose feature sits in the middle, first-and-last-fifth puts both
        cursors on the same surface and reports a meaningless step. The user
        still drags them; this only decides where they begin.
        """
        if self.region_lower.scene() is None:
            return
        span = profile.length
        if span <= 0:
            return

        bounds = self._auto_region_bounds(profile) or ((0.05, 0.25), (0.75, 0.95))
        for region, (lo, hi) in zip((self.region_lower, self.region_upper),
                                    bounds):
            region.blockSignals(True)
            region.setBounds((0.0, span))
            region.setRegion((span * lo, span * hi))
            region.blockSignals(False)

    def _auto_region_bounds(self, profile: Profile):
        """
        Find the middle of each plateau, as fractions of the profile length.

        Returns None when the profile has no two levels -- then the caller
        falls back to fixed fractions and the user places the cursors by hand,
        which is the honest outcome for a profile that has no clear step.
        """
        from afm_copilot.analysis import MIN_SEPARABILITY, _otsu_split

        z = np.asarray(profile.height, dtype=float)
        finite = z[np.isfinite(z)]
        if finite.size < 20:
            return None
        threshold, separability = _otsu_split(finite)
        if separability < MIN_SEPARABILITY:
            return None

        def middle_of_longest(mask: np.ndarray):
            idx = np.flatnonzero(mask)
            if idx.size == 0:
                return None
            runs = np.split(idx, np.flatnonzero(np.diff(idx) != 1) + 1)
            run = max(runs, key=len)
            if run.size < 5:
                return None
            # Middle half of the run, so the cursor stays clear of the edges.
            quarter = run.size // 4
            start, stop = run[quarter], run[run.size - 1 - quarter]
            n = z.size - 1
            return (start / n, stop / n)

        lower = middle_of_longest(z <= threshold)
        upper = middle_of_longest(z > threshold)
        if lower is None or upper is None:
            return None
        return lower, upper

    def _regions_moved(self) -> None:
        # Keep the readout honest while the user drags: the old number is no
        # longer about the region now under the cursor.
        if self._markers:
            self._clear_markers()
            self.verdict.setText("Regions moved -- press Measure step again.")

    def _clear_markers(self) -> None:
        for item in self._markers:
            self.plot.removeItem(item)
        self._markers.clear()

    def _values_in(self, region: pg.LinearRegionItem) -> np.ndarray:
        prof = self._profile
        lo, hi = region.getRegion()
        mask = (prof.distance >= lo) & (prof.distance <= hi)
        return prof.height[mask]

    # ------------------------------------------------------------- measure
    def _measure(self) -> None:
        if self._profile is None:
            self.verdict.setText("No profile yet -- select a scan first.")
            return

        name = (self.ctx.channel_path.name if self.ctx.channel_path
                else "this scan")

        if self.mode.currentText() == MANUAL:
            result = measure_step_between(self._values_in(self.region_lower),
                                          self._values_in(self.region_upper),
                                          source=name)
        else:
            result = measure_step_iso5436(self._profile, source=name)

        self.verdict.setText(result.explain())
        self.verdict.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
            + ("" if result.ok else f" color: {WARN};"))
        self.ctx.log(result.explain())

        self._clear_markers()
        if result.ok:
            self._draw_result(result)

    def _draw_result(self, result) -> None:
        """Show the two levels and the measured height on the plot itself."""
        base = float(np.nanmin(self.ctx.channel.data))
        lower = result.lower_level - base
        upper = result.upper_level - base

        for level in (lower, upper):
            line = pg.InfiniteLine(
                pos=level, angle=0,
                pen=pg.mkPen(WARN, width=1, style=Qt.PenStyle.DashLine))
            self.plot.addItem(line, ignoreBounds=True)
            self._markers.append(line)

        factor, unit = pick_unit(abs(result.value) or 1e-9)
        label = pg.TextItem(
            f"{result.value / factor:.3f} ± "
            f"{result.uncertainty / factor:.3f} {unit}"
            + ("  [marginal]" if result.confidence == "marginal" else ""),
            color=WARN, anchor=(0, 0.5))
        x_at = self._profile.distance[int(0.02 * self._profile.n_points)]
        label.setPos(x_at, (lower + upper) / 2.0)
        self.plot.addItem(label, ignoreBounds=True)
        self._markers.append(label)

        arrow_x = self._profile.distance[int(0.015 * self._profile.n_points)]
        bar = pg.PlotDataItem([arrow_x, arrow_x], [lower, upper],
                              pen=pg.mkPen(WARN, width=2))
        self.plot.addItem(bar, ignoreBounds=True)
        self._markers.append(bar)

    # -------------------------------------------------------------- export
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
