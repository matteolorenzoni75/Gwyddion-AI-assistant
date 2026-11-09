"""Build an operator-facing HTML review from one completed batch run.

The batch JSON is deliberately an audit trail.  This tool makes it reviewable:
one card per scan, grouped with the same family rules used by the analysis,
with the raw and processed topographies side by side.  It does not invent a
measurement when ``readings_for`` declined to make one.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from afm_copilot.analysis import FAMILIES, family_of, readings_for
from afm_copilot.gwy_io import load_height
from afm_copilot.report import _draw_map


FAMILY_LABELS = {
    "terraces": "Terraces and steps",
    "pattern": "Periodic patterns",
    "particles": "Particle layers",
    "objects": "Objects on a background",
    "pits": "Pits and holes",
    "uniform": "Uniform surfaces",
    "other": "No confident family",
    "duplicates": "Repeated areas (set aside)",
    "not topography": "Phase or another non-height channel",
    "unreadable": "Could not be read",
    "discard": "Set aside as unusable",
}


def _safe_text(value: object) -> str:
    return html.escape(str(value))


def _readings_for_row(row: dict, run: Path):
    """Return the sanctioned readings and family for a kept height scan."""
    source = Path(row["source"])
    prepared = run / "prepared" / f"{source.stem}.gwy"
    measured = load_height(prepared if prepared.is_file() else source)
    tip_nm = row.get("tip_radius_nm")
    tip_radius = float(tip_nm) * 1e-9 if tip_nm else None
    readings = readings_for(measured, row.get("measurements") or {}, tip_radius)
    return readings, family_of(readings, row.get("measurements") or {})


def _render_pair(row: dict, run: Path, destination: Path) -> str | None:
    """Render raw and processed topography side by side, when both are honest."""
    source = Path(row["source"])
    try:
        raw = load_height(source)
    except (OSError, ValueError):
        return None

    cleaned = run / "clean" / f"{source.stem}.gwy"
    prepared = run / "prepared" / f"{source.stem}.gwy"
    after = None
    after_title = "After processing"
    # A withheld clean file remains on disk for audit, but is not the result
    # the batch published.  Review must show the same prepared map that the
    # user will receive, rather than making an unsafe technical by-product look
    # approved.
    published = prepared if row.get("curvature_regressed") and prepared.is_file() else cleaned
    if row.get("curvature_regressed"):
        after_title = "Processing withheld — prepared map published"
    if published.is_file():
        try:
            after = load_height(published)
        except (OSError, ValueError):
            pass

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.8), dpi=100)
    _draw_map(axes[0], raw)
    axes[0].set_title("Before processing", fontsize=10, fontweight="bold")
    if after is None:
        axes[1].set_axis_off()
        axes[1].text(0.5, 0.5, "Not processed", ha="center", va="center",
                     fontsize=11, transform=axes[1].transAxes)
    else:
        _draw_map(axes[1], after)
        axes[1].set_title(after_title, fontsize=10, fontweight="bold")
    fig.tight_layout(pad=1.0)
    fig.savefig(destination, dpi=100, facecolor="white")
    plt.close(fig)
    return destination.name


def _reading_markup(readings) -> str:
    if not readings:
        return "<p class='muted'>No feature measurement was appropriate.</p>"
    rows = []
    for reading in readings:
        caveat = (f"<p class='caveat'>{_safe_text(reading.caveat)}</p>"
                  if reading.caveat else "")
        rows.append(
            "<li><strong>{}</strong><br><span>{}</span>{}</li>".format(
                _safe_text(reading.headline), _safe_text(reading.detail), caveat))
    return "<ul class='readings'>" + "".join(rows) + "</ul>"


def _metric_markup(row: dict) -> str:
    before, after = row.get("rms_before_nm"), row.get("rms_after_nm")
    if before is None or after is None:
        return ""
    marker = " <span class='warning'>review</span>" if row.get("over_flattened") else ""
    if row.get("curvature_regressed"):
        marker += " <span class='warning'>technical output withheld</span>"
    return ("<p class='metrics'>Sq/RMS: {:.2f} nm &rarr; {:.2f} nm{}"
            "</p>".format(float(before), float(after), marker))


def _card(row: dict, family: str, readings, image: str | None,
          row_number: int) -> str:
    status = row.get("verdict", "unknown")
    tags = [FAMILY_LABELS.get(family, family), status]
    if row.get("duplicate_of"):
        tags.append("duplicate")
    if row.get("cropped_from"):
        tags.append("cropped incomplete scan")
    if row.get("over_flattened"):
        tags.append("roughness loss needs review")
    if row.get("curvature_regressed"):
        tags.append("curvature regression withheld")

    reasons = "".join(f"<li>{_safe_text(reason)}</li>"
                      for reason in row.get("why", []))
    picture = (f"<img loading='lazy' src='visual_report_assets/{image}' "
               f"alt='Raw and processed topography for scan {row_number}'>"
               if image else
               "<div class='no-image'>No height map is available to display.</div>")
    return """
<article class="scan-card" id="scan-{number}">
  <div class="scan-heading">
    <h3>Scan {number}</h3>
    <div class="tags">{tags}</div>
  </div>
  {picture}
  {metrics}
  <h4>Measurements endorsed by the analysis</h4>
  {readings}
  <h4>Batch decision</h4>
  <ul class="reasons">{reasons}</ul>
</article>""".format(
        number=row_number,
        tags="".join(f"<span>{_safe_text(tag)}</span>" for tag in tags),
        picture=picture,
        metrics=_metric_markup(row),
        readings=_reading_markup(readings),
        reasons=reasons or "<li>No additional warning.</li>",
    )


def build_report(run: Path, destination: Path) -> dict:
    """Write a browsable visual report and return its anonymised summary."""
    batch_path = run / "batch.json"
    if not batch_path.is_file():
        raise ValueError(f"no completed batch report at {batch_path}")
    if destination.exists():
        raise ValueError(f"refusing to overwrite existing report: {destination}")

    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    assets = destination.parent / "visual_report_assets"
    if assets.exists():
        raise ValueError(f"refusing to reuse existing asset folder: {assets}")
    assets.mkdir(parents=True)

    groups: dict[str, list[tuple[int, dict, list, str | None]]] = defaultdict(list)
    failures: list[str] = []
    for number, row in enumerate(batch["results"], 1):
        readings = []
        if row.get("kept"):
            try:
                readings, family = _readings_for_row(row, run)
            except (OSError, ValueError) as exc:
                # The existing batch verdict remains authoritative.  A report
                # rendering failure must never turn into a new measurement.
                family = "other"
                failures.append(f"scan {number}: {exc}")
        elif row.get("duplicate_of"):
            family = "duplicates"
        else:
            family = row.get("verdict", "other")

        image = None
        if family not in {"not topography", "unreadable"}:
            try:
                image = _render_pair(row, run, assets / f"scan-{number:03d}.jpg")
            except (OSError, ValueError) as exc:
                failures.append(f"scan {number}: {exc}")
        groups[family].append((number, row, readings, image))

    counts = Counter({family: len(rows) for family, rows in groups.items()})
    summary = batch
    summary_lines = [
        ("Source scans in report", summary["scans_read"]),
        ("Kept for use", summary["kept"]),
        ("Needed correction", summary["needed_work"]),
        ("Repeated areas set aside", summary["duplicates"]),
        ("Phase / non-height channels", summary.get("not_topography", 0)),
        ("Unreadable", summary["unreadable"]),
        ("Over-flattening warnings", summary.get("over_flattened", 0)),
        ("Curvature-regressed outputs withheld", sum(
            row.get("curvature_regressed", False) for row in summary["results"])),
    ]
    summary_cards = "".join(
        f"<div class='stat'><strong>{value}</strong><span>{_safe_text(label)}</span></div>"
        for label, value in summary_lines)
    family_links = "".join(
        f"<a href='#{_safe_text(family.replace(' ', '-'))}'>{_safe_text(FAMILY_LABELS.get(family, family))} "
        f"({count})</a>" for family, count in sorted(counts.items()))

    sections = []
    for family in sorted(groups, key=lambda key: (key not in FAMILIES, key)):
        cards = "".join(_card(row, family, readings, image, number)
                        for number, row, readings, image in groups[family])
        sections.append(
            f"<section id='{_safe_text(family.replace(' ', '-'))}'><h2>{_safe_text(FAMILY_LABELS.get(family, family))} "
            f"<small>({len(groups[family])})</small></h2>{cards}</section>")

    document = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AFM batch visual review</title>
<style>
body { margin: 0 auto; max-width: 1180px; padding: 24px; color: #18222c;
       background: #f4f6f8; font: 16px/1.45 system-ui, sans-serif; }
header, section { margin-bottom: 34px; }
h1 { margin-bottom: 2px; } h2 { border-bottom: 2px solid #9ab6c7; padding-bottom: 6px; }
h3 { margin: 0; } h4 { margin: 14px 0 4px; font-size: 0.95rem; }
.muted, small { color: #52606d; } .summary { display: flex; flex-wrap: wrap; gap: 10px; }
.stat { min-width: 135px; padding: 10px; background: white; border-left: 5px solid #28748f; }
.stat strong { display: block; font-size: 1.55rem; } .stat span { font-size: .82rem; }
nav { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0; }
nav a, .tags span { background: #dceaf0; color: #173442; padding: 3px 7px; border-radius: 4px; text-decoration: none; font-size: .82rem; }
.scan-card { background: white; margin: 18px 0; padding: 16px; box-shadow: 0 1px 4px #bac4cc; }
.scan-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 5px; }
.scan-card img { display: block; width: 100%; max-width: 900px; margin: 12px auto; }
.readings, .reasons { margin: 4px 0; padding-left: 22px; } .readings li { margin-bottom: 8px; }
.caveat, .warning { color: #8a3f00; } .metrics { font-variant-numeric: tabular-nums; }
.no-image { padding: 30px; margin: 12px 0; text-align: center; background: #edf0f2; color: #52606d; }
@media (max-width: 620px) { body { padding: 12px; } .scan-heading { display: block; } .tags { justify-content: flex-start; margin-top: 8px; } }
</style></head><body>
<header><h1>AFM batch visual review</h1>
<p class="muted">Generated {when}. Each measurement below comes from the existing analysis rules. A refusal is shown as a refusal; an apparent number was not substituted.</p>
<div class="summary">{summary_cards}</div><nav aria-label="Report categories">{family_links}</nav></header>
{sections}
</body></html>"""
    # ``str.format`` would read the CSS braces above as placeholders.  Replace
    # only the four deliberate report markers, leaving the stylesheet literal.
    document = (document
                .replace("{when}", datetime.now().strftime("%Y-%m-%d %H:%M"))
                .replace("{summary_cards}", summary_cards)
                .replace("{family_links}", family_links)
                .replace("{sections}", "".join(sections)))
    destination.write_text(document, encoding="utf-8")
    return {"report": str(destination), "categories": dict(counts),
            "render_failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="completed batch output folder")
    parser.add_argument("--out", type=Path, default=None,
                        help="HTML report path (default: <run>/visual_report.html)")
    args = parser.parse_args()
    destination = args.out or args.run / "visual_report.html"
    summary = build_report(args.run, destination)
    print(f"Visual report: {summary['report']}")
    print("Categories: " + ", ".join(
        f"{name}={count}" for name, count in sorted(summary["categories"].items())))
    if summary["render_failures"]:
        print(f"{len(summary['render_failures'])} scan(s) could not be rendered; "
              "their batch verdicts remain visible in the report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
