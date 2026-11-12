"""Render blind original/mask/operator-target triplets for visual AFM review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from afm_copilot.decide import object_mask, plan_for
from afm_copilot.gwy_io import load_height
from afm_copilot.report import _draw_map


def render(targets: Path, converted: Path, out: Path) -> None:
    pairs = json.loads((targets / "targets.json").read_text(encoding="utf-8"))["pairs"]
    fig, axes = plt.subplots(len(pairs), 3, figsize=(12, 3.8 * len(pairs)),
                             squeeze=False)
    for pair, row in zip(pairs, axes):
        source = load_height(converted / "_gwy" /
                             Path(pair["source"]).with_suffix(".gwy"))
        corrected = load_height(converted / "_gwy" /
                                Path(pair["corrected"]).with_suffix(".gwy"))
        plan = plan_for(source)
        mask = object_mask(plan.levelling.flat)

        _draw_map(row[0], source)
        row[0].set_title(f"Pair {pair['ordinal']}: original", fontweight="bold")
        _draw_map(row[1], source)
        if mask.any():
            row[1].contour(mask.astype(float), levels=[0.5], colors="#04a6d9",
                           linewidths=0.8)
        row[1].set_title(
            f"candidate mask {mask.mean():.1%}; {pair['operator_hint']}",
            fontweight="bold")
        _draw_map(row[2], corrected)
        row[2].set_title("operator-corrected target", fontweight="bold")
    fig.tight_layout(pad=1.3)
    fig.savefig(out, dpi=130, facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", type=Path)
    parser.add_argument("converted", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    render(args.targets, args.converted, args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
