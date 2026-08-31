"""
Reports: the image, the profile it came from, and the number, on one page.

A measurement is only trustworthy if you can see where it came from. So every
page here shows the map with the profile line drawn on it, the profile itself
with the two levels marked, and the value with its uncertainty -- plus any
warning the measurement raised.

Output is PDF via matplotlib, so it goes straight into a lab notebook or a
paper draft.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from afm_copilot.analysis import Aggregate, StepResult, aggregate  # noqa: E402
from afm_copilot.analysis import measure_film_thickness  # noqa: E402
from afm_copilot.gwy_io import Channel  # noqa: E402
from afm_copilot.profile import Profile, plot_profile, profile_across  # noqa: E402
from afm_copilot.render import DEFAULT_CMAP, nice_bar_length, pick_unit  # noqa: E402

ACCENT = "#1f6f5c"
WARN = "#a63a22"


@dataclass
class PageData:
    """Everything one report page needs."""

    channel: Channel
    profile: Profile
    result: StepResult


def _draw_map(ax, channel: Channel, profile: Profile, cmap: str = DEFAULT_CMAP):
    """The height map, with the profile line drawn where it was taken."""
    data = channel.data - np.nanmin(channel.data)
    factor, unit = pick_unit(float(np.nanmax(data)) or 1e-9)
    lo, hi = np.percentile(data[np.isfinite(data)], (0.5, 99.5))

    im = ax.imshow(data / factor, cmap=cmap, origin="lower",
                   vmin=lo / factor, vmax=hi / factor,
                   interpolation="nearest", aspect="equal")
    ax.set_axis_off()

    # The line the profile was taken along, so the reader can see the geometry.
    ax.plot([profile.start_px[0], profile.end_px[0]],
            [profile.start_px[1], profile.end_px[1]],
            color="#00e5ff", linewidth=1.4, alpha=0.95)

    npx = data.shape[1]
    bar_m, label, frac = nice_bar_length(channel.xreal, 0.25)
    margin = 0.05 * npx
    bar_h = max(1.5, 0.013 * npx)
    y = data.shape[0] - margin - bar_h
    ax.add_patch(Rectangle((margin, y), frac * npx, bar_h, facecolor="white",
                           edgecolor="black", linewidth=0.5, zorder=5))
    ax.text(margin + frac * npx / 2, y - 0.015 * npx, label, color="white",
            ha="center", va="top", fontsize=7, fontweight="bold", zorder=6,
            path_effects=_outline())

    cbar = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    cbar.ax.tick_params(labelsize=6, length=2, width=0.4)
    cbar.set_label(f"z ({unit})", fontsize=7)
    cbar.outline.set_linewidth(0.4)


def _outline():
    import matplotlib.patheffects as pe
    return [pe.withStroke(linewidth=1.8, foreground="black")]


def _draw_profile(ax, page: PageData):
    """The profile, with the two measured levels drawn across it."""
    prof, res = page.profile, page.result
    plot_profile(prof, ax=ax, color=ACCENT)

    if not res.ok:
        ax.set_title("no step measured", fontsize=8, color=WARN)
        return

    span = float(np.nanmax(prof.height) - np.nanmin(prof.height))
    z_factor, z_unit = pick_unit(span if span > 0 else 1e-9)
    x_factor, _ = pick_unit(prof.length)

    for level, name in ((res.lower_level, "lower"), (res.upper_level, "upper")):
        ax.axhline(level / z_factor, color=WARN, linestyle="--",
                   linewidth=0.8, alpha=0.85)

    # Annotate the step itself with a double-headed arrow at the left edge.
    x_at = prof.distance[int(0.06 * prof.n_points)] / x_factor
    ax.annotate(
        "", xy=(x_at, res.upper_level / z_factor),
        xytext=(x_at, res.lower_level / z_factor),
        arrowprops=dict(arrowstyle="<->", color=WARN, linewidth=1.0))
    step_factor, step_unit = pick_unit(abs(res.value))
    ax.text(x_at, (res.upper_level + res.lower_level) / 2 / z_factor,
            f"  {res.value / step_factor:.2f} {step_unit}",
            color=WARN, fontsize=7.5, va="center", ha="left")


def _save(fig, pdf: PdfPages, png_path: Path | None):
    """Add a figure to the PDF, and optionally keep it as a standalone PNG."""
    pdf.savefig(fig)
    if png_path is not None:
        png_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(png_path, dpi=200)
    plt.close(fig)


def make_page(pdf: PdfPages, page: PageData, index: int, total: int,
              png_path: Path | None = None):
    """One report page: map on the left, profile on the right, verdict below."""
    fig = plt.figure(figsize=(9.5, 4.6), dpi=200)
    fig.subplots_adjust(left=0.02, right=0.97, top=0.86, bottom=0.24,
                        wspace=0.22)

    ax_map = fig.add_subplot(1, 2, 1)
    _draw_map(ax_map, page.channel, page.profile)

    ax_prof = fig.add_subplot(1, 2, 2)
    _draw_profile(ax_prof, page)

    name = (page.channel.source.name if page.channel.source
            else page.channel.name)
    fig.suptitle(f"{name}    ({index}/{total})", fontsize=10, y=0.965)

    verdict = _wrap(page.result.explain(), width=118)
    fig.text(0.03, 0.02, verdict, fontsize=7.0, va="bottom", family="monospace",
             color="#1c1b18" if page.result.ok else WARN)

    _save(fig, pdf, png_path)


def _shorten(name: str, limit: int = 24) -> str:
    """
    Shorten a filename without losing what distinguishes it.

    Plain truncation is wrong here: AFM filenames differ in their trailing
    index ("... step 1" vs "... step 2"), so cutting the end merges them into
    one indistinguishable label. Cut the middle instead.
    """
    if len(name) <= limit:
        return name
    keep = limit - 3
    head = keep // 2
    return name[:head] + "..." + name[-(keep - head):]


def _wrap(text: str, width: int = 96) -> str:
    """Wrap each line so long warnings stay inside the page."""
    import textwrap
    out = []
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip())
        out.extend(textwrap.wrap(line, width=width,
                                 subsequent_indent=" " * (indent + 2))
                   or [""])
    return "\n".join(out)


def _summary_page(pdf: PdfPages, agg: Aggregate, title: str,
                  pages: list[PageData], png_path: Path | None = None):
    """Opening page: the pooled answer, and the per-image values behind it."""
    fig = plt.figure(figsize=(9.5, 6.6), dpi=200)
    fig.text(0.06, 0.95, title, fontsize=16, fontweight="bold")
    fig.text(0.06, 0.915,
             datetime.now().strftime("Generated %Y-%m-%d %H:%M by AFM Copilot"),
             fontsize=8, color="#57544d")

    fig.text(0.06, 0.86, _wrap(agg.explain()), fontsize=8.5, va="top",
             family="monospace")

    good = [p for p in pages if p.result.ok]
    if good:
        ax = fig.add_axes([0.10, 0.20, 0.80, 0.36])
        factor, unit = pick_unit(abs(agg.mean) if np.isfinite(agg.mean) else 1e-9)
        values = [p.result.value / factor for p in good]
        errors = [p.result.uncertainty / factor for p in good]
        labels = [_shorten(p.channel.source.stem if p.channel.source
                           else p.channel.name) for p in good]
        x = np.arange(len(values))

        ax.errorbar(x, values, yerr=errors, fmt="o", color=ACCENT,
                    capsize=3, markersize=5, linewidth=1)
        ax.axhline(agg.mean / factor, color=WARN, linestyle="--", linewidth=1,
                   label=f"mean {agg.mean / factor:.2f} {unit}")
        if agg.std > 0:
            ax.fill_between([-0.5, len(values) - 0.5],
                            (agg.mean - agg.std) / factor,
                            (agg.mean + agg.std) / factor,
                            color=WARN, alpha=0.10,
                            label=f"+/- 1 sd ({agg.std / factor:.2f} {unit})")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
        ax.set_ylabel(f"step height ({unit})", fontsize=8)
        ax.set_xlim(-0.5, len(values) - 0.5)
        ax.tick_params(labelsize=7)
        ax.grid(True, axis="y", alpha=0.25, linewidth=0.5)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.legend(fontsize=7, frameon=False)

    _save(fig, pdf, png_path)


def build_thickness_report(
    channels: list[Channel],
    out_path: str | Path,
    title: str = "Film thickness",
    band_px: int = 16,
    profile_axis: str = "horizontal",
    png_dir: str | Path | None = None,
) -> dict:
    """
    Measure a film step in every image and write one PDF covering all of them.

    Images where no step can be measured are still given a page, showing why --
    a rejected frame is information, not something to hide.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pages: list[PageData] = []
    for ch in channels:
        result = measure_film_thickness(ch)
        prof = profile_across(ch, profile_axis, position=0.5, band_px=band_px)
        pages.append(PageData(channel=ch, profile=prof, result=result))

    agg = aggregate([p.result for p in pages])

    png = Path(png_dir) if png_dir else None
    with PdfPages(out_path) as pdf:
        _summary_page(pdf, agg, title, pages,
                      png / "00_summary.png" if png else None)
        for i, page in enumerate(pages, 1):
            stem = (page.channel.source.stem if page.channel.source
                    else page.channel.name)
            make_page(pdf, page, i, len(pages),
                      png / f"{i:02d}_{stem}.png" if png else None)

    return {
        "report": str(out_path),
        "n_images": len(pages),
        "n_measured": agg.n_used,
        "mean_m": agg.mean,
        "std_m": agg.std,
        "sem_m": agg.sem,
        "values_m": agg.values,
        "rejected": agg.rejected,
        "summary": agg.explain(),
    }
