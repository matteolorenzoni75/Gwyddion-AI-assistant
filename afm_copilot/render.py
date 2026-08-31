"""
Publication-ready images from AFM channels.

The point of this module is comparability. A folder of AFM scans rendered one
at a time, each auto-scaled to its own range, cannot be compared by eye: the
same colour means a different height in every frame. So the default here is a
**shared colour scale across the whole batch**, a scale bar in physical units,
and a fixed output resolution.

Everything is drawn with matplotlib rather than Gwyddion's own image export,
because `imgexport` is not reachable from PyGwy -- and because this way the
figure, the colour bar and the scale bar are all under our control at an exact
DPI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")  # no display needed; must precede pyplot
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from afm_copilot.gwy_io import Channel  # noqa: E402

# Gwyddion's default palette is a warm gold; "afmhot" is matplotlib's closest
# perceptual match and is what most AFM papers use.
DEFAULT_CMAP = "afmhot"

# Scale bars look wrong at arbitrary lengths. These are the lengths people
# expect to see, in whatever unit fits.
_NICE_STEPS = (1.0, 2.0, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0, 200.0, 500.0)

_UNITS = (
    (1e-12, "pm"),
    (1e-9, "nm"),
    (1e-6, "µm"),
    (1e-3, "mm"),
    (1.0, "m"),
)


def pick_unit(value_m: float) -> tuple[float, str]:
    """Choose the SI prefix that renders `value_m` as a readable number."""
    if not math.isfinite(value_m) or value_m <= 0:
        return 1e-9, "nm"
    for factor, name in _UNITS:
        if value_m < factor * 1000.0:
            return factor, name
    return 1.0, "m"


def nice_bar_length(span_m: float, target_fraction: float = 0.25) -> tuple[float, str, float]:
    """
    Pick a scale-bar length near `target_fraction` of the image width.

    Returns (length in metres, label text, length as a fraction of the image).
    """
    factor, unit = pick_unit(span_m)
    target = span_m * target_fraction / factor
    best = min(_NICE_STEPS, key=lambda s: abs(math.log10(s / target)) if target > 0 else s)
    length_m = best * factor
    label = f"{best:g} {unit}"
    return length_m, label, length_m / span_m


@dataclass
class RenderStyle:
    """Everything about how a batch is drawn, in one place."""

    cmap: str = DEFAULT_CMAP
    dpi: int = 300
    width_in: float = 4.0
    show_colorbar: bool = True
    show_scalebar: bool = True
    show_title: bool = True
    scalebar_fraction: float = 0.25
    # Clip the colour range to these percentiles so a handful of spikes cannot
    # flatten the contrast of an entire batch. Set to (0, 100) for true limits.
    percentile: tuple[float, float] = (0.5, 99.5)
    facecolor: str = "white"
    textcolor: str = "black"


@dataclass
class ColorScale:
    """The z range shared by a batch, in metres."""

    vmin: float
    vmax: float
    unit_factor: float
    unit_name: str

    @property
    def span(self) -> float:
        return self.vmax - self.vmin


def common_color_scale(
    channels: list[Channel],
    percentile: tuple[float, float] = (0.5, 99.5),
    zero_base: bool = True,
) -> ColorScale:
    """
    One z range covering the whole batch.

    Each channel is first shifted so its own minimum sits at zero, which is
    what makes separately-levelled scans comparable at all -- otherwise an
    arbitrary z offset in one file would dominate the range.
    """
    lows, highs = [], []
    for ch in channels:
        data = ch.data
        finite = data[np.isfinite(data)]
        if finite.size == 0:
            continue
        if zero_base:
            finite = finite - finite.min()
        lo, hi = np.percentile(finite, percentile)
        lows.append(lo)
        highs.append(hi)

    if not lows:
        raise ValueError("no finite data in any channel")

    vmin, vmax = float(min(lows)), float(max(highs))
    if vmax <= vmin:
        vmax = vmin + 1e-12
    factor, unit = pick_unit(vmax - vmin)
    return ColorScale(vmin=vmin, vmax=vmax, unit_factor=factor, unit_name=unit)


def scale_spread(channels: list[Channel]) -> float:
    """
    Ratio between the largest and smallest z range in a batch.

    A shared colour scale is only meaningful when this is modest. At a ratio of
    100 the shallowest scan is rendered in the bottom 1% of the colour map and
    reads as a flat rectangle -- technically correct, practically useless.
    """
    ranges = [ch.z_range for ch in channels if math.isfinite(ch.z_range) and ch.z_range > 0]
    if len(ranges) < 2:
        return 1.0
    return max(ranges) / min(ranges)


def group_by_scale(
    channels: list[Channel],
    max_ratio: float = 8.0,
) -> list[list[Channel]]:
    """
    Split a mixed batch into groups whose z ranges are within `max_ratio`.

    Images inside a group share one colour scale and stay directly comparable;
    across groups they do not. This is the honest compromise for a folder
    holding, say, DNA at 5 nm and a grating at 4 um -- forcing those onto one
    scale serves nobody.
    """
    usable = [c for c in channels if math.isfinite(c.z_range) and c.z_range > 0]
    leftovers = [c for c in channels if c not in usable]
    if not usable:
        return [channels]

    ordered = sorted(usable, key=lambda c: c.z_range)
    groups: list[list[Channel]] = [[ordered[0]]]
    for ch in ordered[1:]:
        if ch.z_range / groups[-1][0].z_range <= max_ratio:
            groups[-1].append(ch)
        else:
            groups.append([ch])

    if leftovers:
        groups[0].extend(leftovers)
    return groups


def group_label(group: list[Channel]) -> str:
    """A directory-safe name describing a group's z range."""
    lo = min(c.z_range for c in group)
    hi = max(c.z_range for c in group)
    factor, unit = pick_unit(hi)
    return f"z_{lo / factor:.3g}-{hi / factor:.3g}{unit}".replace("µ", "u")


def _prepare(channel: Channel, zero_base: bool = True) -> np.ndarray:
    data = np.array(channel.data, dtype=float)
    if zero_base:
        finite = data[np.isfinite(data)]
        if finite.size:
            data = data - finite.min()
    return data


def _crop_to_fov(channel: Channel, data: np.ndarray, fov_m: float) -> tuple[np.ndarray, float]:
    """
    Centre-crop so every image shows the same physical field of view.

    Scans of different sizes are otherwise incomparable no matter how the
    colours are handled: a 5 um and a 50 um scan drawn the same size imply
    features ten times different. Images already smaller than `fov_m` are left
    alone, and their true extent is returned.
    """
    if fov_m <= 0 or fov_m >= channel.xreal:
        return data, channel.xreal

    keep = int(round(data.shape[1] * fov_m / channel.xreal))
    keep = max(8, min(keep, data.shape[1]))
    cy, cx = data.shape[0] // 2, data.shape[1] // 2
    half = keep // 2
    y0, y1 = max(0, cy - half), min(data.shape[0], cy + half)
    x0, x1 = max(0, cx - half), min(data.shape[1], cx + half)
    return data[y0:y1, x0:x1], channel.xreal * (x1 - x0) / data.shape[1]


def render_channel(
    channel: Channel,
    out_path: str | Path,
    scale: ColorScale,
    style: RenderStyle | None = None,
    fov_m: float | None = None,
    title: str | None = None,
) -> Path:
    """Draw one channel to an image file using a caller-supplied colour scale."""
    style = style or RenderStyle()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = _prepare(channel)
    extent_m = channel.xreal
    if fov_m:
        data, extent_m = _crop_to_fov(channel, data, fov_m)

    display = data / scale.unit_factor
    vmin = scale.vmin / scale.unit_factor
    vmax = scale.vmax / scale.unit_factor

    # Lay the figure out in inches, then convert to figure fractions, so the
    # image stays square and the colour bar sits beside it rather than on top
    # of the data -- at any DPI or figure width.
    title_h = 0.32 if style.show_title else 0.06
    cbar_w = 0.62 if style.show_colorbar else 0.0
    pad = 0.06
    img_w = style.width_in - cbar_w - 2 * pad
    fig_w = style.width_in
    fig_h = img_w + title_h + pad

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=style.dpi,
                     facecolor=style.facecolor)
    ax = fig.add_axes([pad / fig_w, pad / fig_h, img_w / fig_w, img_w / fig_h])
    ax.set_axis_off()

    im = ax.imshow(display, cmap=style.cmap, vmin=vmin, vmax=vmax,
                   origin="lower", interpolation="nearest", aspect="equal")

    if style.show_scalebar:
        bar_m, label, frac = nice_bar_length(extent_m, style.scalebar_fraction)
        npx = data.shape[1]
        bar_px = frac * npx
        margin = 0.045 * npx
        bar_h = max(1.5, 0.014 * npx)
        y = data.shape[0] - margin - bar_h
        ax.add_patch(Rectangle((margin, y), bar_px, bar_h,
                               facecolor="white", edgecolor="black",
                               linewidth=0.5, zorder=5))
        ax.text(margin + bar_px / 2.0, y - 0.012 * npx, label,
                color="white", ha="center", va="top", zorder=6,
                fontsize=8, fontweight="bold",
                path_effects=_outline())

    if style.show_colorbar:
        cax = fig.add_axes([(pad + img_w + 0.10) / fig_w,
                            (pad + 0.10 * img_w) / fig_h,
                            0.13 / fig_w,
                            (0.80 * img_w) / fig_h])
        cbar = fig.colorbar(im, cax=cax)
        cbar.ax.tick_params(labelsize=6, colors=style.textcolor, length=2,
                            width=0.4, pad=1.5)
        cbar.set_label(f"z ({scale.unit_name})", fontsize=7,
                       color=style.textcolor, labelpad=2)
        cbar.outline.set_linewidth(0.4)

    if style.show_title:
        fig.text(pad / fig_w + (img_w / fig_w) / 2.0,
                 1.0 - (0.10 / fig_h),
                 title or Path(channel.source or "").stem,
                 ha="center", va="top", fontsize=8.5, color=style.textcolor)

    fig.savefig(out_path, dpi=style.dpi, facecolor=style.facecolor,
                pad_inches=0)
    plt.close(fig)
    return out_path


def _outline():
    """White-on-image text needs an outline to stay legible on any palette."""
    import matplotlib.patheffects as pe
    return [pe.withStroke(linewidth=1.8, foreground="black")]


def render_batch(
    channels: list[Channel],
    out_dir: str | Path,
    style: RenderStyle | None = None,
    shared_scale: bool = True,
    fov_m: float | None = None,
    fmt: str = "jpg",
) -> dict:
    """
    Render a batch of channels to comparable images.

    With `shared_scale` (the default) every image uses one z range, so equal
    colours mean equal heights across the set. Returns a summary describing
    what was drawn, including the scale actually used -- which belongs in any
    figure caption.
    """
    style = style or RenderStyle()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not channels:
        raise ValueError("nothing to render")

    scale = common_color_scale(channels, style.percentile) if shared_scale else None

    written = []
    for ch in channels:
        per_scale = scale or common_color_scale([ch], style.percentile)
        stem = Path(ch.source).stem if ch.source else ch.name
        out_path = out_dir / f"{stem}.{fmt}"
        render_channel(ch, out_path, per_scale, style, fov_m=fov_m, title=stem)
        written.append({
            "file": str(out_path),
            "channel": ch.name,
            "source": str(ch.source) if ch.source else None,
            "xreal_m": ch.xreal,
            "z_range_m": ch.z_range,
            "rms_m": ch.rms,
        })

    used = scale or common_color_scale(channels, style.percentile)
    spread = scale_spread(channels)
    return {
        "n_images": len(written),
        "output_dir": str(out_dir),
        "shared_scale": shared_scale,
        "scale_spread": spread,
        "scale_warning": (
            f"z ranges in this batch differ by a factor of {spread:.0f}. "
            "With one shared scale the shallowest scans will look flat. "
            "Consider --auto-group."
            if shared_scale and spread > 20 else None),
        "z_min": used.vmin,
        "z_max": used.vmax,
        "z_unit": used.unit_name,
        "z_min_display": used.vmin / used.unit_factor,
        "z_max_display": used.vmax / used.unit_factor,
        "dpi": style.dpi,
        "cmap": style.cmap,
        "field_of_view_m": fov_m,
        "images": written,
    }
