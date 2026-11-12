"""Print how the current pre-processing planner routes the blind corpus.

This is a measurement tool, not a label optimiser.  The family stored in the
export baseline is shown only as a regression reference; it is not treated as
ground truth and it never enters ``plan_for``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from afm_copilot.analysis import height_levels
from afm_copilot.decide import (_levels_are_flat, _subtract_dominant_facet,
                                plan_for)
from afm_copilot.features import subtract_background
from afm_copilot.gwy_io import Channel, load_height


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=Path("export"))
    args = parser.parse_args()

    baseline = json.loads(
        (args.export / "baseline.json").read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in baseline["scans"]}
    rows: list[tuple[str, str, str, bool, float, int, int, bool,
                     int, bool]] = []
    for path in sorted((args.export / "scans").glob("scan-*.gwy")):
        entry = entries[path.stem]
        if not entry.get("kept"):
            continue
        channel = load_height(path)
        plan = plan_for(channel)
        raw_levels = len(height_levels(channel))
        plane_flat = subtract_background(np.asarray(channel.data, dtype=float), 1)
        plane_channel = Channel(
            name=channel.name,
            data=plane_flat,
            xreal=channel.xreal,
            yreal=channel.yreal,
        )
        plane_levels = len(height_levels(plane_channel))
        plane_levels_flat = _levels_are_flat(
            plane_flat, height_levels(plane_channel))
        facet_flat = _subtract_dominant_facet(channel.data)
        facet_channel = Channel(
            name=channel.name,
            data=facet_flat,
            xreal=channel.xreal,
            yreal=channel.yreal,
        )
        facet_level_values = height_levels(facet_channel)
        facet_levels = len(facet_level_values)
        facet_levels_flat = _levels_are_flat(facet_flat, facet_level_values)
        rows.append((path.stem, entry.get("family", ""), plan.recipe_key,
                     plan.has_terraces, plan.object_fraction,
                     raw_levels, plane_levels, plane_levels_flat,
                     facet_levels, facet_levels_flat))

    print("routes")
    for route, count in Counter(row[2] for row in rows).most_common():
        print(f"  {route:24s} {count:2d}")

    print("\nroute x baseline family (baseline is not ground truth)")
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for _, family, route, _, _, _, _, _, _, _ in rows:
        matrix[route][family] += 1
    for route in sorted(matrix):
        details = ", ".join(
            f"{family or '(none)'}={count}"
            for family, count in matrix[route].most_common())
        print(f"  {route:24s} {details}")

    print("\nterrace references and automatic terrace decisions")
    for (name, family, route, terraces, fraction, raw_levels, plane_levels,
         plane_levels_flat, facet_levels, facet_levels_flat) in rows:
        if family == "terraces" or terraces:
            print(f"  {name}\tbaseline={family}\troute={route}\t"
                  f"terraces={terraces}\tfeature_fraction={fraction:.3f}\t"
                  f"levels_raw={raw_levels}\tlevels_after_plane={plane_levels}\t"
                  f"plane_levels_flat={plane_levels_flat}\t"
                  f"levels_after_facet={facet_levels}\t"
                  f"facet_levels_flat={facet_levels_flat}")

    print("\nall plane-level candidates")
    for (name, family, route, _, fraction, _, plane_levels,
         plane_levels_flat, facet_levels, facet_levels_flat) in rows:
        if plane_levels >= 2 or facet_levels >= 2:
            print(f"  {name}\tbaseline={family}\troute={route}\t"
                  f"feature_fraction={fraction:.3f}\t"
                  f"levels_after_plane={plane_levels}\t"
                  f"plane_levels_flat={plane_levels_flat}\t"
                  f"levels_after_facet={facet_levels}\t"
                  f"facet_levels_flat={facet_levels_flat}")

    print("\nmasked routes with broad apparent feature coverage")
    for name, family, route, _, fraction, _, _, _, _, _ in rows:
        if route.startswith("isolate-") and fraction >= 0.08:
            print(f"  {name}\tbaseline={family}\troute={route}\t"
                  f"feature_fraction={fraction:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
