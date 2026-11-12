"""Generate cautious Gwyddion correction candidates for operator comparison.

Input: PRIVATE original/manual pair manifest, never the 97k-image archive.
Output: private operator-review derivatives in AFM_Copilot_Workspace.
Only accepted safe_auto recipe operations run. No automatic approval or
training. Originals, manual images and other source channels are untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

from afm_copilot.bridge import GwyBridge
from afm_copilot.correction_gate import gate_recipe
from afm_copilot.decide import plan_for
from afm_copilot.directory_map import WORKSPACE
from afm_copilot.gwy_io import load_height, save_height
from afm_copilot.labeler import _load
from afm_copilot.manual_pairs import PRIVATE_ROOT, save_private
from afm_copilot.ops.recipes import get_recipe
from afm_copilot.quality import assess

MANIFEST = PRIVATE_ROOT / "PRIVATE_manual_pair_candidates.json"
OUTPUT = WORKSPACE / "runs"
AUDIT = PRIVATE_ROOT / "PRIVATE_automatic_correction_audit.jsonl"
# This conservative pilot excludes advanced curved fits, unverified scars,
# despiking and interpolation whenever the gate requests review.
MAX_RMS_CHANGE = 0.65


def _id(path: Path) -> str:
    stat = path.stat()
    identifier = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:22]


def _calibrated(channel) -> bool:
    return bool(
        channel.z_unit == "m" and channel.xy_unit == "m"
        and math.isfinite(channel.xreal) and math.isfinite(channel.yreal)
        and channel.xreal > 0 and channel.yreal > 0
        and channel.xres >= 32 and channel.yres >= 32
        and np.isfinite(channel.data).all()
    )


def _manifest_rows(manifest: Path) -> list[dict]:
    content = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(content, dict) or not isinstance(content.get("pairs"), list):
        raise ValueError("Private comparison manifest has no valid pairs array")
    rows = content["pairs"]
    if not all(isinstance(row, dict) and row.get("original") and row.get("manual")
               for row in rows):
        raise ValueError("Malformed private original/manual pairs")
    return rows


def _is_source_dir(path: Path, originals: list[Path]) -> bool:
    return any(path == source or path in source.parents for source in originals)


def process_one(
    row: dict, *, output: Path = OUTPUT, scratch: Path | None = None,
    importer=_load, bridge_factory=GwyBridge
) -> dict:
    """Return a private result with no raw-path info in caller's stdout."""
    raw = Path(row["original"]).expanduser().resolve()
    manual = Path(row["manual"]).expanduser().resolve()
    if not raw.is_file() or not manual.is_file():
        return {"state": "held_missing_input"}
    # Never accidentally process a manually corrected image as raw.
    if raw == manual:
        return {"state": "held_same_source"}
    if row.get("automated") and Path(row["automated"]).is_file():
        return {"state": "existing", "automated": row["automated"]}
    output = output.expanduser().resolve()
    # Output must be separated from each input's containing directory.
    # In particular, do not write derivatives anywhere under an AFM raw folder.
    if any(output == p.parent or p.parent in output.parents
           or output == p or output in p.parents for p in (raw, manual)):
        return {"state": "held_output_inside_source"}

    identity = _id(raw)
    dest = output / identity
    expected = dest / "corrected" / "height.gwy"
    if expected.exists():
        # Never silently overwrite a previous generated file, and do not
        # automatically trust leftovers from an interrupted/failed run.
        return {"state": "held_existing_unverified_derivative"}
    work = (scratch or PRIVATE_ROOT / "scratch").expanduser().resolve() / identity
    work.mkdir(parents=True, exist_ok=True)
    source_channel, _ = importer(raw, work)
    if not _calibrated(source_channel):
        return {"state": "held_calibration"}
    plan = plan_for(source_channel)
    quality = assess(source_channel)
    gate = gate_recipe(plan, quality, calibration_verified=True, channel_role="height")
    safe = [item["operation"] for item in gate["operations"]
            if item["status"] == "safe_auto"]
    if quality.verdict == "discard":
        return {"state": "held_quality"}
    if not safe:
        return {"state": "held_requires_review", "recipe": plan.recipe_key}

    original_recipe = get_recipe(plan.recipe_key)
    # This path never creates an operator mask: mask removal is not a
    # valid stand-alone step. Mask-dependent fitting belongs to the
    # explicitly approved masked_compare path.
    selected = tuple(
        key for key in original_recipe.steps
        if key in safe and key != "remove_mask"
    )
    if not selected:
        return {"state": "held_requires_review", "recipe": plan.recipe_key}

    # The derivative contains ONLY the verified topography; original
    # multichannel file (phase/amplitude/current/trace/retrace) stays intact.
    source = work / "height.gwy"
    save_height(source_channel, source)
    derived_recipe = replace(original_recipe, steps=selected)
    dest.mkdir(parents=True, exist_ok=True)
    result = bridge_factory().run_recipe(
        derived_recipe, [source], dest / "corrected"
    )
    entries = result.get("results") or []
    if len(entries) != 1 or not entries[0].get("ok"):
        return {"state": "held_bridge_failure", "recipe": plan.recipe_key}
    applied = entries[0].get("steps", [])
    if any(not entry.get("applied") for entry in applied) or len(applied) != len(selected):
        return {"state": "held_partial_failure", "recipe": plan.recipe_key}
    produced = Path(entries[0]["output"]).resolve()
    if not produced.is_file() or produced != expected:
        return {"state": "held_output_mismatch"}
    revised = load_height(produced)
    if revised.data.shape != source_channel.data.shape or (
        revised.xreal != source_channel.xreal or revised.yreal != source_channel.yreal
    ) or not np.isfinite(revised.data).all():
        return {"state": "held_changed_geometry"}
    before = float(source_channel.rms)
    after = float(revised.rms)
    if not math.isfinite(after) or (
        before > 0 and abs(after - before) / before > MAX_RMS_CHANGE
    ):
        return {"state": "held_large_rms_change"}
    row["automated"] = str(produced)
    return {
        "state": "generated_for_review", "recipe": plan.recipe_key,
        "steps_applied": list(selected),
        "steps_held": [i["operation"] for i in gate["operations"]
                       if i["status"] != "safe_auto"],
        "source_rms_nm": round(before * 1e9, 4),
        "output_rms_nm": round(after * 1e9, 4),
        "automated": str(produced),
        "requires_operator_validation": True,
    }


def run_batch(
    manifest: Path = MANIFEST, *, output: Path = OUTPUT,
    scratch: Path | None = None, processor=process_one,
) -> dict:
    rows = _manifest_rows(manifest)
    # Keep this workflow intentionally bounded: it is for the curated
    # comparison corpus, never the 97k-file archive. Existing automatic
    # associations are skipped by process_one(), so reruns fill only gaps.
    if len(rows) > 64:
        raise ValueError("Comparison run limited to 64 operator-reviewed candidate pairs")
    if output.expanduser().resolve() == manifest.parent.resolve():
        raise ValueError("Output cannot be the private manifest folder")
    counts = {}
    details = []
    for index, row in enumerate(rows):
        try:
            result = processor(row, output=output, scratch=scratch)
        except Exception as error:
            result = {"state": "held_exception", "type": type(error).__name__}
        state = result["state"]
        counts[state] = counts.get(state, 0) + 1
        # Private audit retains index and paths. No source filenames on stdout.
        details.append({"index": index, **result})
        # Durable private checkpoint after each scan.
        save_private({
            "schema_version": 1,
            "pairs": rows,
            "source": "auto_candidates_with_operator_review_required",
        }, manifest)
    audit = (manifest.parent / AUDIT.name)
    with audit.open("a", encoding="utf-8") as stream:
        for record in details:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "pairs_examined": len(rows), "states": dict(sorted(counts.items())),
        "new_auto_associations": counts.get("generated_for_review", 0),
        "automatic_approval": False,
        "source_scans_modified": False,
        "training_performed": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--confirm",
        choices=("RUN_COMPARISON_CANDIDATES", "RUN_8_CANDIDATES"),
        required=True,
        help="Explicit opt-in for the bounded private comparison corpus.")
    args = parser.parse_args(argv)
    if not args.manifest.is_file():
        print(json.dumps({"error": "private_comparison_manifest_missing"}))
        return 2
    report = run_batch(args.manifest, output=args.output)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
