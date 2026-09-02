"""
The image viewer: the centre of the window and the reason a GUI exists at all.

What this gives that the command line cannot: a draggable histogram for the z
range (the standard SPM idiom -- you find the features by squeezing the colour
scale onto them), pan and zoom, a profile line you position by hand, and the
live readout under the cursor.

Heights are held in metres and converted for display only, so nothing is
converted twice.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from afm_copilot.gwy_io import Channel
from afm_copilot.render import pick_unit

# Gwyddion's palette is a warm gold; these are the matplotlib maps closest to
# what AFM papers use, plus greyscale for judging flatness honestly.
COLORMAPS = ["afmhot", "inferno", "viridis", "magma", "gray", "cividis"]


class ScanViewer(QWidget):
    """Displays one channel, with the controls that make a scan readable."""

    #: Emitted when the profile line moves: (x0, y0, x1, y1) in pixels.
    profile_moved = Signal(float, float, float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.channel: Channel | None = None
        self._unit_factor = 1e-9
        self._unit_name = "nm"
        self._build()

    # ------------------------------------------------------------------ ui
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        controls = QHBoxLayout()
        controls.setContentsMargins(6, 4, 6, 0)

        self.cmap_box = QComboBox()
        self.cmap_box.addItems(COLORMAPS)
        self.cmap_box.currentTextChanged.connect(self._apply_colormap)
        controls.addWidget(QLabel("Colour"))
        controls.addWidget(self.cmap_box)

        self.profile_check = QCheckBox("Profile line")
        self.profile_check.setChecked(True)
        self.profile_check.toggled.connect(self._toggle_profile)
        controls.addWidget(self.profile_check)

        controls.addStretch(1)
        self.readout = QLabel("")
        self.readout.setStyleSheet("color: palette(mid); font-family: "
                                   "Consolas, monospace;")
        controls.addWidget(self.readout)
        layout.addLayout(controls)

        # The numbers that describe the scan, always visible. Without these the
        # image is only a picture -- you cannot tell a 500 nm feature from a
        # 5 nm one by colour alone.
        self.stats = QLabel("No scan loaded")
        self.stats.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stats.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; "
            "padding: 3px 8px; color: palette(text);")
        layout.addWidget(self.stats)

        self.glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw, 1)

        self.plot = self.glw.addPlot(row=0, col=0)
        self.plot.setAspectLocked(True)
        self.plot.invertY(False)
        self.plot.showAxes(True, showValues=(True, False, False, True))
        self.plot.setLabel("bottom", "x", units="m")
        self.plot.setLabel("left", "y", units="m")

        self.image = pg.ImageItem(axisOrder="row-major")
        self.plot.addItem(self.image)

        # The draggable histogram: squeeze it to bring out low features.
        self.hist = pg.HistogramLUTItem(image=self.image)
        self.glw.addItem(self.hist, row=0, col=1)

        # A line the user drags to choose where the profile is taken.
        self.profile_line = pg.LineSegmentROI([[0, 0], [1, 1]], pen=pg.mkPen(
            "#00d5ff", width=2))
        self.profile_line.sigRegionChanged.connect(self._profile_changed)
        self.plot.addItem(self.profile_line)

        self.scalebar = pg.ScaleBar(size=1e-6, suffix="m")
        self.scalebar.setParentItem(self.plot.getViewBox())
        self.scalebar.anchor((1, 1), (1, 1), offset=(-20, -20))

        self._apply_colormap(self.cmap_box.currentText())
        self.plot.scene().sigMouseMoved.connect(self._mouse_moved)

    # --------------------------------------------------------------- data
    def show_channel(self, channel: Channel | None) -> None:
        """Display a channel, or clear the view when given None."""
        self.channel = channel
        if channel is None:
            self.image.clear()
            self.readout.setText("")
            self.stats.setText("No scan loaded")
            return

        data = np.asarray(channel.data, dtype=float)
        finite = data[np.isfinite(data)]
        base = float(finite.min()) if finite.size else 0.0
        zeroed = data - base

        span = float(finite.max() - finite.min()) if finite.size else 1e-9
        self._unit_factor, self._unit_name = pick_unit(span or 1e-9)
        display = zeroed / self._unit_factor

        self.image.setImage(display, autoLevels=False)
        # Map pixels onto real metres so the axes and the scale bar are true.
        self.image.setRect(0.0, 0.0, channel.xreal, channel.yreal)

        lo, hi = np.percentile(display[np.isfinite(display)], (0.5, 99.5))
        if hi <= lo:
            hi = lo + 1e-12
        self.hist.setLevels(lo, hi)
        self.hist.axis.setLabel(f"z ({self._unit_name})")

        self._place_profile_line(channel)
        self._fit_scalebar(channel)

        # Set the range explicitly rather than calling autoRange(): the scale
        # bar is a child of the view box and drags the automatic range far
        # outside the data, which left the image an invisible speck.
        self.plot.getViewBox().setRange(
            xRange=(0.0, channel.xreal), yRange=(0.0, channel.yreal),
            padding=0.02)
        self._update_stats(channel)

    def _update_stats(self, channel: Channel) -> None:
        """The numbers that make the picture a measurement."""
        scan_f, scan_u = pick_unit(channel.xreal)
        px_f, px_u = pick_unit(channel.pixel_size)
        z_f, z_u = pick_unit(channel.z_range or 1e-9)
        rms_f, rms_u = pick_unit(channel.rms or 1e-12)

        self.stats.setText(
            f"{channel.name}    "
            f"{channel.xres} x {channel.yres} px    "
            f"scan {channel.xreal / scan_f:.4g} x "
            f"{channel.yreal / scan_f:.4g} {scan_u}    "
            f"pixel {channel.pixel_size / px_f:.4g} {px_u}    "
            f"z range {channel.z_range / z_f:.4g} {z_u}    "
            f"RMS {channel.rms / rms_f:.4g} {rms_u} (raw)")
        self.stats.setToolTip(
            "RMS here is the raw standard deviation of the heights. It "
            "includes any tilt or bow still in the image, so it is not a "
            "roughness measurement until the scan has been levelled -- and "
            "levelling itself lowers it further.")

    def _place_profile_line(self, channel: Channel) -> None:
        """
        Put the profile line across the middle of a newly loaded scan.

        LineSegmentROI has no setPoints; its two endpoints are free handles
        moved individually, in parent (plot) coordinates.
        """
        y = channel.yreal / 2.0
        handles = self.profile_line.getHandles()
        if len(handles) < 2:
            return
        self.profile_line.blockSignals(True)
        self.profile_line.setPos(pg.Point(0.0, 0.0))
        self.profile_line.movePoint(handles[0], pg.Point(0.0, y),
                                    coords="parent", finish=False)
        self.profile_line.movePoint(handles[1], pg.Point(channel.xreal, y),
                                    coords="parent", finish=True)
        self.profile_line.blockSignals(False)
        self._profile_changed()

    def _fit_scalebar(self, channel: Channel) -> None:
        target = channel.xreal / 4.0
        factor, _ = pick_unit(target)
        nice = min((1, 2, 5, 10, 20, 50, 100, 200, 500),
                   key=lambda s: abs(s * factor - target))
        self.scalebar.size = nice * factor
        self.scalebar.text.setText(pg.siFormat(nice * factor, suffix="m"))
        self.scalebar.updateBar()

    # ------------------------------------------------------------ handlers
    def _apply_colormap(self, name: str) -> None:
        try:
            cmap = pg.colormap.get(name, source="matplotlib")
        except Exception:
            cmap = pg.colormap.get("viridis")
        self.hist.gradient.setColorMap(cmap)

    def _toggle_profile(self, on: bool) -> None:
        self.profile_line.setVisible(on)
        if on:
            self._profile_changed()

    def _profile_changed(self) -> None:
        if self.channel is None:
            return
        handles = self.profile_line.getSceneHandlePositions()
        pts = [self.plot.getViewBox().mapSceneToView(h[1]) for h in handles]
        if len(pts) < 2:
            return
        w, h = self.channel.xres, self.channel.yres
        px = [(p.x() / self.channel.xreal * (w - 1),
               p.y() / self.channel.yreal * (h - 1)) for p in pts]
        self.profile_moved.emit(px[0][0], px[0][1], px[1][0], px[1][1])

    def _mouse_moved(self, pos) -> None:
        if self.channel is None or not self.plot.sceneBoundingRect().contains(pos):
            self.readout.setText("")
            return
        pt = self.plot.getViewBox().mapSceneToView(pos)
        ch = self.channel
        col = int(pt.x() / ch.xreal * ch.xres)
        row = int(pt.y() / ch.yreal * ch.yres)
        if not (0 <= col < ch.xres and 0 <= row < ch.yres):
            self.readout.setText("")
            return
        z = ch.data[row, col] - float(np.nanmin(ch.data))
        self.readout.setText(
            f"x {pt.x() * 1e6:.3f} um   y {pt.y() * 1e6:.3f} um   "
            f"z {z / self._unit_factor:.3f} {self._unit_name}")
