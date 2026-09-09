# -*- coding: utf-8 -*-
"""
Build the corpus handed to another agent, and the baseline it is judged by.

The full run is 240 converted scans and 453 MB, which moves badly and is more
than anyone needs. What an agent needs is every *kind* of scan: one of each
family, the awkward cases the knowledge notes argue about, and the failures --
the interrupted frame, the saturated one, the one that was set aside, the
channels that are not height at all.

Alongside the files goes a baseline: what this code says about each of them
today. That is not ground truth and must never be read as ground truth. It is a
regression net. Change a detector, regenerate, and the diff is the argument.

    python tools/make_export_corpus.py --out export

Nothing here reads a filename to decide anything, and neither should anything
downstream: the corpus is blind on purpose.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

# The scans the knowledge notes and AGENTS.md argue about by name. They are
# named here so a selection by family cannot quietly drop the evidence behind a
# decision -- not because their names say anything about what they contain.
ARGUED_ABOUT = [
    "SKPM_Muk_per_GRAP0003good",     # the flake whose mask came back 8% of 28%
    "Single object high z step 2",   # the block the owner masked by hand
    "121127-Topography-005",         # 150 nm of belly, now 1.4
    "terrace - 130909Topography003", # named for terraces, measures none
    "140307Topography021",           # fibres once reported as a 35 nm step
    "Calibration grating - Vertical",
    "Silaver Film - Kiril 20nm005",  # measures 20.0 nm, nothing read the name
    "DVD240122003005",               # round even bumps that are not particles
    "Nanoparticles 1",
    "fibers 2 trace",                # feedback bistability
    "IN2O3PAA0000",                  # over-flattening flag
    "ebl pattern retrace",           # over-flattening flag
    "ALEX_AS_SGHS_Br_I0023",         # XY piezo lag, still open
    "150113Topography001",
    "130408Topography001",
]

PER_FAMILY = 4


def _copy_without_the_name(source: Path, destination: Path,
                           original: str) -> None:
    """
    Copy a container, leaving every trace of its own name behind.

    Renaming the file is not enough, and this is the whole reason the check
    exists. A scan carries its identity in three places, and each was found
    only by looking:

      * `/filename` -- the full original path, in all 56 files
      * `/N/log` -- Gwyddion's processing log, which can quote paths
      * `/N/meta/BaseName` -- the Asylum metadata, which holds the sample's
        own name: `ALEX_AS_SGHS_Br_I`, `SKPM_Muk_per_GRAP`

    The last one is why the scrub is written against the original name rather
    than a list of keys: the next vendor will hide it somewhere else, and a
    value that echoes the filename is suspect wherever it sits.

    What stays is the rest of `/N/meta` -- scan rate, image mode, set point,
    servo gains. That is the instrument describing itself, it identifies
    nobody, and it is what a future multichannel or drift correction needs.
    """
    import gwyfile

    tokens = {piece.strip("()").lower()
              for piece in original.replace("_", " ").replace("-", " ").split()
              if len(piece.strip("()")) >= 4}
    tokens.add(original.lower())

    obj = gwyfile.load(str(source))
    for key in [k for k in obj.keys()
                if "filename" in k.lower() or k.endswith("/log")]:
        del obj[key]

    for key in list(obj.keys()):
        meta = obj[key]
        if not key.endswith("/meta") or not hasattr(meta, "keys"):
            continue
        for field in list(meta.keys()):
            text = str(meta[field]).lower()
            if any(token in text for token in tokens):
                del meta[field]

    obj.tofile(str(destination))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=r"C:\AFM_Copilot\out\batch_run",
                        help="a completed batch output directory")
    parser.add_argument("--out", default="export", type=Path)
    parser.add_argument("--per-family", type=int, default=PER_FAMILY)
    args = parser.parse_args()

    from afm_copilot.analysis import family_of, readings_for
    from afm_copilot.gwy_io import load_height

    run = Path(args.run)
    rows = json.loads((run / "batch.json").read_text())["results"]
    by_name = {r["name"]: r for r in rows}

    chosen: dict[str, str] = {}          # name -> why it is in

    def take(name: str, why: str) -> None:
        if name in by_name and (run / "_gwy" / (name + ".gwy")).is_file():
            chosen.setdefault(name, why)

    for name in ARGUED_ABOUT:
        take(name, "argued about in the knowledge notes")

    # Every verdict, not only the kept ones: an agent that never sees a
    # discarded scan cannot tell whether it would discard the right things.
    # A few of each is the point -- the batch has 32 repeats and the
    # thirty-second teaches nothing the third did not.
    seen: dict[str, int] = {}

    def some(kind: str, name: str, why: str, cap: int = 3) -> None:
        if seen.get(kind, 0) >= cap:
            return
        before = len(chosen)
        take(name, why)
        if len(chosen) > before:
            seen[kind] = seen.get(kind, 0) + 1

    for entry in rows:
        if entry.get("cropped_from"):
            some("cropped", entry["name"],
                 "interrupted, cropped to the part with data")
        elif entry.get("duplicate_of"):
            some("repeat", entry["name"], "the same area scanned again")
        elif not entry.get("kept"):
            # No cap: there is only one set aside and eight non-height
            # channels, and both classes are small and irreplaceable.
            take(entry["name"], "not kept -- see its verdict")
        elif entry.get("clipped"):
            some("clipped", entry["name"],
                 "saturated: the scanner ran out of travel")
        elif entry.get("over_flattened"):
            some("over-flattened", entry["name"],
                 "the cleaning took more than it should have")

    # Then a few of each family, so every route through the code is exercised.
    counts: dict[str, int] = {}
    for entry in sorted((r for r in rows if r.get("kept")),
                        key=lambda r: r["name"].lower()):
        cleaned = run / "clean" / (entry["name"] + ".gwy")
        if not cleaned.is_file():
            continue
        measurements = entry.get("measurements") or {}
        try:
            radius = entry.get("tip_radius_nm")
            readings = readings_for(load_height(str(cleaned)), measurements,
                                    (radius * 1e-9) if radius else None)
        except Exception:                                      # noqa: BLE001
            continue
        family = family_of(readings, measurements)
        if counts.get(family, 0) >= args.per_family:
            continue
        counts[family] = counts.get(family, 0) + 1
        take(entry["name"], "family: " + family)

    scans = args.out / "scans"
    scans.mkdir(parents=True, exist_ok=True)
    for stale in scans.glob("*.gwy"):
        stale.unlink()

    # Renamed, and for two reasons that happen to agree.
    #
    # The first is other people's: the original filenames carry collaborators'
    # names attached to unpublished samples, and this repository is public.
    # The second is the project's own rule -- the corpus is blind, and nothing
    # may infer content from a name. Neutral ids make that true by
    # construction instead of by discipline: there is no name left to read.
    #
    # The mapping is written next to the corpus and is git-ignored, so the
    # originals stay recoverable on the machine that made it.
    order = sorted(chosen)
    mapping = {"scan-%03d" % i: n for i, n in enumerate(order, start=1)}
    as_id = {n: i for i, n in mapping.items()}

    baseline = []
    total = 0
    for name in order:
        source = run / "_gwy" / (name + ".gwy")
        scan_id = as_id[name]
        _copy_without_the_name(source, scans / (scan_id + ".gwy"), name)
        total += source.stat().st_size

        entry = by_name[name]
        record = {
            "name": scan_id,
            "in_the_corpus_because": chosen[name],
            "kept": bool(entry.get("kept")),
            "verdict": entry.get("verdict"),
            "why": entry.get("why"),
            "recipe": entry.get("recipe"),
            # These point at other scans by name, so they are translated too --
            # a single untranslated one would undo the whole point.
            "cropped_from": as_id.get(entry.get("cropped_from") or "",
                                      "another scan, not in this corpus"
                                      if entry.get("cropped_from") else None),
            "duplicate_of": as_id.get(entry.get("duplicate_of") or "",
                                      "another scan, not in this corpus"
                                      if entry.get("duplicate_of") else None),
            "measurements": entry.get("measurements") or {},
        }
        cleaned = run / "clean" / (name + ".gwy")
        if cleaned.is_file():
            try:
                radius = entry.get("tip_radius_nm")
                readings = readings_for(load_height(str(cleaned)),
                                        record["measurements"],
                                        (radius * 1e-9) if radius else None)
                record["family"] = family_of(readings, record["measurements"])
                record["readings"] = [
                    {"kind": r.kind, "headline": r.headline} for r in readings]
            except Exception as error:                         # noqa: BLE001
                record["readings_failed"] = str(error)[:200]
        baseline.append(record)

    (args.out / "baseline.json").write_text(
        json.dumps({
            "what_this_is": "What this code says about these scans today. A "
                            "regression net, NOT ground truth. Regenerate with "
                            "tools/make_export_corpus.py and read the diff.",
            "the_names_are_ids": "Deliberately. The corpus is blind: nothing "
                                 "may infer what a scan contains from what it "
                                 "is called, and there is nothing here to "
                                 "infer it from.",
            "scans": baseline,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    (args.out / "original-names.json").write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")

    print("%d scansioni, %.1f MB" % (len(baseline), total / 1e6))
    for family, n in sorted(counts.items()):
        print("   %-12s %d" % (family, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
