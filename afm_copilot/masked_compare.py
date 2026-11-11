"""Run an explicitly approved masked background fit on ONE AFM scan.

Only a private operator-approved mask can trigger this operation. Gwyddion
uses MASK_EXCLUDE during polylevel, followed by mask removal. No pixels
are interpolated, no source or manual data are overwritten, and previous
automatic candidates stay available. No model is trained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np

from afm_copilot.auto_compare import MANIFEST, OUTPUT, _calibrated, _id, _manifest_rows
from afm_copilot.bridge import GwyBridge
from afm_copilot.gwy_io import load_height, save_height
from afm_copilot.labeler import _load
from afm_copilot.manual_pairs import PRIVATE_ROOT, save_private
from afm_copilot.ops.recipes import get_recipe


MASK_ROOT = PRIVATE_ROOT / "masks"


def save_approved_mask(index: int, raw: Path, mask: np.ndarray,
                       *, threshold_nm: float, mode: str,
                       remove_scars: bool = False) -> Path:
    """Store exactly the binary mask the operator saw, never a raw image."""
    raw = raw.resolve()
    identity = _id(raw)
    folder = MASK_ROOT / (identity + "-" + uuid.uuid4().hex[:10])
    folder.mkdir(parents=True, exist_ok=False)
    binary = np.asarray(mask, dtype=bool)
    np.save(folder / "mask.npy", binary, allow_pickle=False)
    metadata = {
        "schema_version": 1, "index": index, "source_identity": identity,
        "source": str(raw), "shape": list(binary.shape),
        "threshold_nm": float(threshold_nm), "polarity": mode,
        "operator_approved": True,
        "remove_scars": bool(remove_scars),
        "masked_fraction": float(binary.mean()),
    }
    (folder / "approved.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8")
    return folder / "approved.json"


def run_masked(index: int, approval: Path, *, manifest: Path = MANIFEST,
               output: Path = OUTPUT, importer=_load,
               bridge_factory=GwyBridge) -> dict:
    rows = _manifest_rows(manifest)
    if not 0 <= index < len(rows):
        raise ValueError("Unknown comparison pair")
    record = json.loads(approval.read_text(encoding="utf-8"))
    row = rows[index]
    raw = Path(row["original"]).resolve()
    manual = Path(row["manual"]).resolve()
    if not raw.is_file() or not manual.is_file() or raw == manual:
        raise ValueError("Original/manual pair not available")
    if not record.get("operator_approved") or record.get("index") != index:
        raise ValueError("Mask is not approved for this comparison pair")
    if record.get("source_identity") != _id(raw) or Path(record["source"]).resolve() != raw:
        raise ValueError("Original has changed since mask approval")
    if approval.resolve().parent.parent != MASK_ROOT.resolve():
        raise ValueError("Mask approval must be stored in private mask folder")
    mask = np.load(approval.parent / "mask.npy", allow_pickle=False)
    if mask.dtype != np.bool_ or list(mask.shape) != record.get("shape"):
        raise ValueError("Mask shape or dtype invalid")
    fraction = float(mask.mean())
    if not (0.01 <= fraction <= 0.40) or np.min(1.0-mask.mean(axis=1)) < 0.25:
        raise ValueError("Insufficient unmasked background")
    if abs(fraction - record["masked_fraction"]) > 1e-7:
        raise ValueError("Mask coverage no longer matches approval")
    output = output.resolve()
    for p in (raw, manual):
        if output == p.parent or p.parent in output.parents or output in p.parents:
            raise ValueError("Output folder overlaps source")
    work = approval.parent / "working"
    work.mkdir(exist_ok=True)
    channel, _ = importer(raw, work)
    if not _calibrated(channel) or channel.data.shape != mask.shape:
        raise ValueError("Calibration or mask geometry mismatch")

    # Reproducible versioned candidate, never overwrite old automatic result.
    version = uuid.uuid4().hex[:12]
    dest = output / _id(raw) / "masked_review" / version
    dest.mkdir(parents=True, exist_ok=False)
    input_gwy = work / "masked_input.gwy"
    save_height(channel, input_gwy, mask=mask)
    selected_steps = ("plane_around_objects", "remove_mask")
    if record.get("remove_scars", False):
        # Explicitly opted-in by the operator; unmasked scar detection runs
        # AFTER the background fit so the mask cannot bias line correction.
        selected_steps += ("remove_scars",)
    recipe = replace(
        get_recipe("isolate-objects-flat"),
        key="operator-masked-plane",
        steps=selected_steps,
    )
    report = bridge_factory().run_recipe(
        recipe, [input_gwy], dest)
    results = report.get("results") or []
    if len(results) != 1 or not results[0].get("ok"):
        raise RuntimeError("Gwyddion masked correction failed")
    steps = results[0].get("steps", [])
    if len(steps) != len(selected_steps) or any(
        not step.get("applied") for step in steps
    ):
        raise RuntimeError("Gwyddion did not execute the complete masked fit")
    product = Path(results[0]["output"]).resolve()
    if product != (dest / "masked_input.gwy").resolve() or not product.is_file():
        raise RuntimeError("Gwyddion output path mismatch")
    corrected = load_height(product)
    if corrected.data.shape != channel.data.shape or not np.isfinite(corrected.data).all():
        raise RuntimeError("Processed image geometry or values invalid")
    if (not math.isclose(corrected.xreal, channel.xreal, rel_tol=1e-8)
        or not math.isclose(corrected.yreal, channel.yreal, rel_tol=1e-8)):
        raise RuntimeError("Processing changed physical scan dimensions")
    # No automatic selection as ground truth. This is only the third column.
    row["automated"] = str(product)
    save_private({
        "schema_version": 1, "pairs": rows,
        "source": "operator_masked_gwyddion_candidate",
        "requires_manual_validation": True,
    }, manifest)
    audit_path = PRIVATE_ROOT / "PRIVATE_masked_corrections.jsonl"
    with audit_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "index": index, "raw": str(raw), "manual": str(manual),
            "approved_mask": str(approval), "output": str(product),
            "threshold_nm": record["threshold_nm"], "mode": record["polarity"],
            "masked_fraction": fraction, "remove_scars": bool(record.get("remove_scars")),
            "steps": [s["key"] for s in steps],
            "operator_approved_final_correction": False,
        }) + "\n")
    return {
        "status": "generated_for_review", "index": index,
        "masked_fraction": round(fraction, 4),
        "step_count": len(selected_steps),
        "original_modified": False, "manual_modified": False,
        "requires_operator_approval": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_masked(args.index, args.approval)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({"status": "held", "error": type(error).__name__,
                          "message": str(error)[:200]}))
        return 3
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
