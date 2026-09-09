# -*- coding: utf-8 -*-
"""
Recompute what the code says about the corpus, and print only what moved.

This is the net under every change. Run it before touching anything, so you
know the state you are starting from; run it after, and read the difference.
A change that moves nothing here has not been tested — say so rather than
claiming it works.

    python tools/diff_export_baseline.py

Exit code is 0 when nothing moved and 1 when something did. That is a
statement of fact, not a verdict: a difference can be the improvement you
were aiming for. Read it before you accept it.

Needs no Gwyddion. The cleaned surfaces are in the corpus precisely so that
this can run anywhere.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def readings_now(cleaned: Path, measurements: dict, tip_radius_nm) -> list[dict]:
    """The readings this code produces today for one cleaned surface."""
    from afm_copilot.analysis import family_of, readings_for
    from afm_copilot.gwy_io import load_height

    channel = load_height(str(cleaned))
    radius = (tip_radius_nm * 1e-9) if tip_radius_nm else None
    readings = readings_for(channel, measurements, radius)
    return ([{"kind": r.kind, "headline": r.headline} for r in readings],
            family_of(readings, measurements))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=REPO / "export")
    parser.add_argument("--verbose", action="store_true",
                        help="list the scans that did not move as well")
    args = parser.parse_args()

    baseline = json.loads((args.export / "baseline.json").read_text("utf-8"))

    moved, unchanged, skipped = [], 0, []
    for record in baseline["scans"]:
        name = record["name"]
        cleaned = args.export / "clean" / (name + ".gwy")
        if not cleaned.is_file():
            # No cleaned surface: the scan was not kept, or it is not height
            # at all. Nothing to recompute, and that is not a failure.
            skipped.append(name)
            continue

        try:
            readings, family = readings_now(
                cleaned, record.get("measurements") or {},
                record.get("tip_radius_nm"))
        except Exception as error:                             # noqa: BLE001
            moved.append((name, "raised %s" % type(error).__name__,
                          str(error)[:120]))
            continue

        was = [(r["kind"], r["headline"]) for r in record.get("readings", [])]
        now = [(r["kind"], r["headline"]) for r in readings]

        if was == now and record.get("family") == family:
            unchanged += 1
            if args.verbose:
                print("   = %-12s %s" % (name, "; ".join(h for _, h in now)))
            continue

        moved.append((name, was, now))
        if record.get("family") != family:
            moved[-1] = (name, was + [("family", record.get("family"))],
                         now + [("family", family)])

    print("%d invariate, %d cambiate, %d senza superficie pulita da ricalcolare"
          % (unchanged, len(moved), len(skipped)))

    for name, was, now in moved:
        print()
        print("  %s" % name)
        if isinstance(was, str):
            print("      %s: %s" % (was, now))
            continue
        for line in _differences(was, now):
            print("      %s" % line)

    return 1 if moved else 0


def _differences(was: list[tuple], now: list[tuple]) -> list[str]:
    """Only the lines that are not in both, marked with which side they are on."""
    before, after = set(was), set(now)
    lines = []
    for kind, headline in was:
        if (kind, headline) not in after:
            lines.append("- [%s] %s" % (kind, headline))
    for kind, headline in now:
        if (kind, headline) not in before:
            lines.append("+ [%s] %s" % (kind, headline))
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
