"""Measure whether proposed feature masks leave a defensible background.

The table is evidence for morphology routing, not a classifier.  Baseline
families are printed only for review and never enter the measurements.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from afm_copilot.decide import object_mask, plan_for
from afm_copilot.gwy_io import load_height
from afm_copilot.morphology import background_support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=Path("export"))
    parser.add_argument("--probe", type=Path)
    args = parser.parse_args()

    payload = json.loads(
        (args.export / "baseline.json").read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in payload["scans"]}
    paths = sorted((args.export / "scans").glob("scan-*.gwy"))
    if args.probe:
        paths.append(args.probe)

    print("id\tbaseline\troute\tpolarity\tmask\tbackground\tworst_row\t"
          "largest_region\troughness_ratio\tgradient_ratio\ttexture_coverage")
    for path in paths:
        entry = entries.get(path.stem, {})
        if entry and not entry.get("kept"):
            continue
        try:
            channel = load_height(path)
        except (OSError, ValueError):
            continue
        plan = plan_for(channel)
        mask = object_mask(plan.levelling.flat)
        evidence = background_support(plan.levelling.flat, mask)
        if plan.sunken_fraction > 2 * plan.raised_fraction:
            polarity = "pores"
        elif plan.raised_fraction > 2 * plan.sunken_fraction:
            polarity = "raised"
        else:
            polarity = "mixed"
        metrics = evidence.as_dict()
        values = []
        for key in ("unmasked_fraction", "worst_row_support",
                    "largest_region_fraction", "roughness_ratio",
                    "gradient_ratio", "texture_coverage"):
            value = metrics[key]
            values.append("nan" if value != value else f"{value:.3f}")
        label = entry.get("family", "probe")
        print(f"{path.stem}\t{label}\t{plan.recipe_key}\t{polarity}\t"
              f"{mask.mean():.3f}\t" + "\t".join(values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
