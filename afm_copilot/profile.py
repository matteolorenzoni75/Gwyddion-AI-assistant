"""
Line profiles: extract, export, plot.

A profile is how an AFM measurement becomes a number. The image shows you that
there is a step; the profile is what you measure it from.

Two things here go beyond drawing a line through the data:

  * **Band averaging.** A single-pixel profile carries the full pixel noise. A
    profile averaged across a band of rows perpendicular to the line has the
    same shape with far less scatter, and it is what anyone measuring a step
    height does by hand anyway.
  * **Gwyddion-compatible export.** `to_text()` writes the same two-column
    format Gwyddion's own profile tool exports, so the numbers can go straight
    into whatever the group already uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from afm_copilot.gwy_io import Channel


@dataclass
class Profile:
    """Heights sampled along a straight line across a channel."""

    distance: np.ndarray        # metres from the start of the line
    height: np.ndarray          # metres
    start_px: tuple[float, float]
    end_px: tuple[float, float]
    band_px: int
    channel_name: str = ""
    source: Path | None = None
    meta: dict = field(default_factory=dict)

    @property
    def length(self) -> float:
        return float(self.distance[-1]) if self.distance.size else 0.0

    @property
    def n_points(self) -> int:
        return int(self.distance.size)

    def to_text(self, path: str | Path, comment: str = "") -> Path:
        """
        Write the two-column text Gwyddion's profile export produces.

        Values stay in SI units, as Gwyddion writes them, so the file can be
        read by anything that already handles Gwyddion profiles.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Profile exported by AFM Copilot",
            f"# Channel: {self.channel_name}",
            f"# Source: {self.source if self.source else 'unknown'}",
            f"# Line: ({self.start_px[0]:.1f}, {self.start_px[1]:.1f}) px "
            f"-> ({self.end_px[0]:.1f}, {self.end_px[1]:.1f}) px",
            f"# Band averaged over {self.band_px} pixel(s)",
        ]
        if comment:
            lines.extend(f"# {ln}" for ln in comment.splitlines())
        lines.append("# x [m]\tz [m]")
        for x, z in zip(self.distance, self.height):
            lines.append(f"{x:.10g}\t{z:.10g}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def _bilinear(data: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Sample an array at fractional positions, clamped to its bounds."""
    h, w = data.shape
    rows = np.clip(rows, 0, h - 1)
    cols = np.clip(cols, 0, w - 1)

    r0 = np.floor(rows).astype(int)
    c0 = np.floor(cols).astype(int)
    r1 = np.clip(r0 + 1, 0, h - 1)
    c1 = np.clip(c0 + 1, 0, w - 1)
    dr = rows - r0
    dc = cols - c0

    return (data[r0, c0] * (1 - dr) * (1 - dc)
            + data[r0, c1] * (1 - dr) * dc
            + data[r1, c0] * dr * (1 - dc)
            + data[r1, c1] * dr * dc)


def extract_profile(
    channel: Channel,
    start: tuple[float, float] = (0.0, 0.5),
    end: tuple[float, float] = (1.0, 0.5),
    band_px: int = 1,
    n_samples: int | None = None,
    fractional: bool = True,
) -> Profile:
    """
    Sample heights along a line.

    `start` and `end` are (x, y). With `fractional` (the default) they are
    fractions of the image, so (0, 0.5) -> (1, 0.5) is a horizontal line across
    the middle regardless of pixel count. Set `fractional=False` to give pixel
    coordinates instead.

    `band_px` averages that many parallel lines centred on the requested one,
    which cuts noise without changing the shape of what you are measuring.
    """
    data = channel.data
    h, w = data.shape

    if fractional:
        x0, y0 = start[0] * (w - 1), start[1] * (h - 1)
        x1, y1 = end[0] * (w - 1), end[1] * (h - 1)
    else:
        x0, y0 = start
        x1, y1 = end

    dx, dy = x1 - x0, y1 - y0
    length_px = float(np.hypot(dx, dy))
    if length_px < 1:
        raise ValueError("profile line is shorter than one pixel")

    n = int(n_samples or round(length_px) + 1)
    t = np.linspace(0.0, 1.0, n)
    cols = x0 + t * dx
    rows = y0 + t * dy

    band_px = max(1, int(band_px))
    if band_px == 1:
        heights = _bilinear(data, rows, cols)
    else:
        # Offsets perpendicular to the line, so the band follows the line's
        # direction rather than always being vertical.
        nx, ny = -dy / length_px, dx / length_px
        offsets = np.arange(band_px) - (band_px - 1) / 2.0
        stack = [_bilinear(data, rows + o * ny, cols + o * nx) for o in offsets]
        heights = np.mean(stack, axis=0)

    # Convert pixel distance to metres using the true pixel pitch.
    px_size_x = channel.xreal / w
    px_size_y = channel.yreal / h
    step_m = float(np.hypot(dx * px_size_x, dy * px_size_y)) / max(1, n - 1)
    distance = np.arange(n) * step_m

    return Profile(
        distance=distance,
        height=np.asarray(heights, dtype=float),
        start_px=(float(x0), float(y0)),
        end_px=(float(x1), float(y1)),
        band_px=band_px,
        channel_name=channel.name,
        source=channel.source,
    )


def profile_across(channel: Channel, axis: str = "horizontal",
                   position: float = 0.5, band_px: int = 1) -> Profile:
    """A straight profile across the middle (or any fraction) of the image."""
    if axis.startswith("h"):
        return extract_profile(channel, (0.0, position), (1.0, position),
                               band_px=band_px)
    if axis.startswith("v"):
        return extract_profile(channel, (position, 0.0), (position, 1.0),
                               band_px=band_px)
    raise ValueError("axis must be 'horizontal' or 'vertical'")


def plot_profile(profile: Profile, ax=None, unit_z: str | None = None,
                 color: str = "#1f6f5c", label: str | None = None):
    """
    Draw a profile onto a matplotlib axis, in readable units.

    Returns the axis so the caller can keep composing -- the report places this
    beside the image it came from.
    """
    import matplotlib.pyplot as plt

    from afm_copilot.render import pick_unit

    if ax is None:
        _, ax = plt.subplots(figsize=(5, 2.2))

    x_factor, x_unit = pick_unit(profile.length)
    span = float(np.nanmax(profile.height) - np.nanmin(profile.height))
    z_factor, z_name = pick_unit(span if span > 0 else 1e-9)
    if unit_z:
        z_name = unit_z

    ax.plot(profile.distance / x_factor, profile.height / z_factor,
            color=color, linewidth=1.1, label=label)
    ax.set_xlabel(f"distance ({x_unit})", fontsize=8)
    ax.set_ylabel(f"height ({z_name})", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.25, linewidth=0.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    return ax
