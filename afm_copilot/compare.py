"""
Side-by-side report: every scan as it arrived, and as it came out.

Two columns, one row per scan, with the numbers underneath each image and a
plain statement of what changed. The point is to make over-processing visible:
a correction that halved the roughness while flattening a real feature looks
obviously wrong side by side, and looks like success in a table of numbers.

Which is why the change column never says "improved". It says what moved.
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

from afm_copilot.analysis import plane_fraction  # noqa: E402
from afm_copilot.gwy_io import Channel, load_height  # noqa: E402
from afm_copilot.ops import parse_log, read_log  # noqa: E402
from afm_copilot.render import pick_unit  # noqa: E402
from afm_copilot.report import _draw_map, _save, _shorten, _wrap  # noqa: E402

ACCENT = "#1f6f5c"
WARN = "#a63a22"


@dataclass
class Pair:
    """One scan before and after, with the history behind each."""

    name: str
    raw: Channel
    processed: Channel | None
    raw_log: list[str]
    processed_log: list[str]

    @property
    def steps_applied(self) -> list[str]:
        """The operations that ran here, beyond whatever the scan arrived with."""
        before = len(parse_log(self.raw_log))
        return [s["gwy_func"] for s in parse_log(self.processed_log)][before:]


def measurements(channel: Channel) -> dict:
    """The numbers worth putting in both columns."""
    return {
        "z_range": channel.z_range,
        "rms": channel.rms,
        "tilt": plane_fraction(channel.data),
        "min": float(np.nanmin(channel.data)),
        "max": float(np.nanmax(channel.data)),
    }


def _fmt(value: float, unit_of: float | None = None) -> str:
    factor, unit = pick_unit(abs(unit_of if unit_of is not None else value) or 1e-9)
    return f"{value / factor:.3f} {unit}"


def _column_text(channel: Channel, stats: dict) -> str:
    return "\n".join([
        f"z range  {_fmt(stats['z_range'])}",
        f"RMS      {_fmt(stats['rms'])}",
        f"tilt     {stats['tilt'] * 100:.0f}% of the height variation",
        f"size     {channel.xres} x {channel.yres} px, "
        f"{_fmt(channel.xreal)} wide",
    ])


def _change_text(pair: Pair, before: dict, after: dict) -> str:
    """What moved, stated without calling it good or bad."""
    lines = []

    if before["rms"] > 0:
        pct = 100.0 * (after["rms"] - before["rms"]) / before["rms"]
        lines.append(f"RMS {pct:+.1f}%   ({_fmt(before['rms'])} -> "
                     f"{_fmt(after['rms'], before['rms'])})")
    if before["z_range"] > 0:
        pct = 100.0 * (after["z_range"] - before["z_range"]) / before["z_range"]
        lines.append(f"z range {pct:+.1f}%")

    lines.append(f"tilt {before['tilt'] * 100:.0f}% -> {after['tilt'] * 100:.0f}%")

    steps = pair.steps_applied
    lines.append("applied: " + (", ".join(steps) if steps else "nothing"))

    # The two readings that are worth a second look rather than a verdict.
    if before["rms"] > 0 and after["rms"] < before["rms"] * 0.5:
        lines.append("NOTE: more than half the height variation was removed. "
                     "Check the image: levelling takes real structure with it.")
    if before["tilt"] < 0.05 and steps:
        lines.append("NOTE: this scan arrived with no tilt -- the instrument "
                     "had already levelled it.")
    return "\n".join(lines)


def _page(pdf: PdfPages, pair: Pair, index: int, total: int,
          png_path: Path | None = None):
    fig = plt.figure(figsize=(10.5, 5.6), dpi=200)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.86, bottom=0.30,
                        wspace=0.18)

    before = measurements(pair.raw)
    ax_raw = fig.add_subplot(1, 2, 1)
    _draw_map(ax_raw, pair.raw)
    ax_raw.set_title("raw", fontsize=11, fontweight="bold", color=ACCENT)

    ax_out = fig.add_subplot(1, 2, 2)
    if pair.processed is not None:
        after = measurements(pair.processed)
        _draw_map(ax_out, pair.processed)
        ax_out.set_title("after processing", fontsize=11, fontweight="bold",
                         color=ACCENT)
    else:
        after = None
        ax_out.set_axis_off()
        ax_out.text(0.5, 0.5, "not processed", ha="center", va="center",
                    fontsize=11, color=WARN, transform=ax_out.transAxes)

    fig.suptitle(f"{pair.name}    ({index}/{total})", fontsize=11, y=0.965)

    fig.text(0.04, 0.255, _column_text(pair.raw, before), fontsize=8,
             va="top", family="monospace")
    if after is not None:
        fig.text(0.52, 0.255, _column_text(pair.processed, after), fontsize=8,
                 va="top", family="monospace")
        fig.text(0.04, 0.115, _wrap(_change_text(pair, before, after), 130),
                 fontsize=8, va="top", family="monospace", color="#1c1b18")

    _save(fig, pdf, png_path)


def _summary(pdf: PdfPages, pairs: list[Pair], title: str,
             png_path: Path | None = None):
    fig = plt.figure(figsize=(10.5, 7.0), dpi=200)
    fig.text(0.05, 0.95, title, fontsize=16, fontweight="bold")
    fig.text(0.05, 0.915,
             datetime.now().strftime("Generated %Y-%m-%d %H:%M by AFM Copilot"),
             fontsize=8, color="#57544d")

    rows = []
    for p in pairs:
        b = measurements(p.raw)
        a = measurements(p.processed) if p.processed is not None else None
        rows.append((
            _shorten(p.name, 30),
            f"{b['rms'] * 1e9:.2f}",
            f"{a['rms'] * 1e9:.2f}" if a else "-",
            f"{b['tilt'] * 100:.0f}%",
            f"{a['tilt'] * 100:.0f}%" if a else "-",
            f"{len(p.steps_applied)}",
        ))

    ax = fig.add_axes([0.05, 0.10, 0.90, 0.76])
    ax.set_axis_off()
    table = ax.table(
        cellText=rows,
        colLabels=["scan", "RMS raw\n(nm)", "RMS after\n(nm)",
                   "tilt raw", "tilt after", "steps"],
        cellLoc="right", colLoc="center", loc="upper center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.6)
    for (row, col), cell in table.get_celld().items():
        cell.set_linewidth(0.4)
        if row == 0:
            cell.set_facecolor("#e7e4dc")
            cell.set_text_props(fontweight="bold")
        if col == 0:
            cell.set_text_props(ha="left")

    fig.text(0.05, 0.06,
             _wrap("A fall in RMS is not by itself an improvement: every "
                   "levelling step removes some real roughness along with the "
                   "artifact. Read this table beside the images, not instead "
                   "of them.", 140),
             fontsize=8, va="top", color="#57544d")

    _save(fig, pdf, png_path)


def build_comparison_report(
    raw_dir: str | Path,
    processed_dir: str | Path,
    out_path: str | Path,
    title: str = "Raw and processed",
    png_dir: str | Path | None = None,
) -> dict:
    """
    Pair every processed scan with the file it came from and report both.

    Pairing is by filename, which is how the processing step names its output.
    A raw scan with no processed counterpart still gets a row, saying so.
    """
    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pairs: list[Pair] = []
    for raw_file in sorted(raw_dir.glob("*.gwy")):
        try:
            raw = load_height(raw_file)
        except (ValueError, OSError):
            continue
        out_file = processed_dir / raw_file.name
        processed = None
        processed_log: list[str] = []
        if out_file.is_file():
            try:
                processed = load_height(out_file)
                processed_log = read_log(out_file)
            except (ValueError, OSError):
                processed = None
        pairs.append(Pair(name=raw_file.stem, raw=raw, processed=processed,
                          raw_log=read_log(raw_file),
                          processed_log=processed_log))

    if not pairs:
        raise ValueError(f"no scans found in {raw_dir}")

    png = Path(png_dir) if png_dir else None
    with PdfPages(out_path) as pdf:
        _summary(pdf, pairs, title, png / "00_summary.png" if png else None)
        for i, pair in enumerate(pairs, 1):
            _page(pdf, pair, i, len(pairs),
                  png / f"{i:02d}_{pair.name}.png" if png else None)

    return {
        "report": str(out_path),
        "n_scans": len(pairs),
        "n_processed": sum(1 for p in pairs if p.processed is not None),
        "scans": [
            {
                "name": p.name,
                "raw": measurements(p.raw),
                "processed": (measurements(p.processed)
                              if p.processed is not None else None),
                "steps": p.steps_applied,
            }
            for p in pairs
        ],
    }
