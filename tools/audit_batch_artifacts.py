"""Measure existing artifact signals across a completed batch without altering it.

This is deliberately an audit, not a repair.  In particular, broad depressed
regions are candidates for operator review: ``lift_region`` can preserve their
fine texture, but it still changes their measured height and must not run by
default.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from afm_copilot import frame, quality, repair
from afm_copilot.decide import object_mask, plan_for
from afm_copilot.gwy_io import load_height


def _check(result: quality.Quality, name: str) -> quality.Check:
    return next(check for check in result.checks if check.name == name)


def _slow_axis_belly_nm(data: np.ndarray) -> float:
    """Residual curvature of the mean slow-axis profile, in nanometres.

    A planar background has a straight mean profile.  This deliberately does
    not reward a lower RMS: it asks only whether a correction wrote more bow
    into the frame along the direction that row operations can disturb.
    """
    profile = np.nanmean(np.asarray(data, dtype=float), axis=1)
    good = np.isfinite(profile)
    if good.sum() < 3:
        return float("nan")
    axis = np.linspace(-1.0, 1.0, profile.size)
    slope = np.polyfit(axis[good], profile[good], 1)
    return float(np.std(profile[good] - np.polyval(slope, axis[good])) * 1e9)


def audit(run: Path) -> dict:
    """Recompute current signals, one kept height scan at a time."""
    batch = json.loads((run / "batch.json").read_text(encoding="utf-8"))
    rows = []
    for ordinal, entry in enumerate(batch["results"], 1):
        if not entry.get("kept"):
            continue
        source = Path(entry["source"])
        try:
            channel = load_height(source)
            cropped, _ = frame.crop_to_data(channel)
            plan = plan_for(cropped)
            verdict = quality.assess(cropped, levelling=plan.levelling)
            feedback = _check(verdict, "feedback")
            rattle = _check(verdict, "rattle")
            dishes = repair.find_dishes(plan.levelling.flat)
            # Measure the adaptive candidate even if the conservative plan did
            # not yet call it an object.  This exposes the important failure
            # mode where a single tall feature covers <3% at its thresholded
            # top but needs protecting while the background is fitted.
            mask = object_mask(plan.levelling.flat)
        except (OSError, ValueError, StopIteration) as exc:
            rows.append({"ordinal": ordinal, "audit_error": str(exc)[:160]})
            continue
        rows.append({
            "ordinal": ordinal,
            "feedback_score": round(feedback.value, 4),
            "feedback_verdict": feedback.verdict,
            "rattle_fraction": round(rattle.value, 6),
            "rattle_verdict": rattle.verdict,
            "dish_fraction": round(float(dishes.mean()), 6),
            "dish_pixels": int(dishes.sum()),
            "recipe": plan.recipe_key,
            "has_objects": plan.has_objects,
            "background_degree": plan.background_degree,
            # Row correction can only use a mask when each row retains enough
            # true background.  These figures let the batch separate a compact
            # object with a short directional tail from a wide automatic mask;
            # the latter must never be passed to masked line matching.
            "mask_fraction": round(float(mask.mean()), 6),
            "least_clear_row_fraction": round(float(1.0 - mask.mean(axis=1).max()), 6),
            "rows_less_than_half_clear": int((mask.mean(axis=1) > 0.50).sum()),
            "over_flattened": bool(entry.get("over_flattened")),
        })
        cleaned = run / "clean" / f"{source.stem}.gwy"
        before_path = run / "prepared" / f"{source.stem}.gwy"
        if not before_path.is_file():
            before_path = source
        if cleaned.is_file():
            try:
                before = load_height(before_path)
                after = load_height(cleaned)
                if before.data.shape == after.data.shape:
                    rows[-1]["belly_before_nm"] = round(
                        _slow_axis_belly_nm(before.data), 4)
                    rows[-1]["belly_after_nm"] = round(
                        _slow_axis_belly_nm(after.data), 4)
            except (OSError, ValueError):
                pass
    return {"n_kept": len(rows), "scans": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="completed batch output folder")
    parser.add_argument("--out", type=Path, default=None,
                        help="audit JSON path (default: <run>/artifact_audit.json)")
    args = parser.parse_args()
    output = args.out or args.run / "artifact_audit.json"
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing audit: {output}")
    result = audit(args.run)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    scans = [row for row in result["scans"] if "audit_error" not in row]
    feedback = sum(row["feedback_verdict"] != "ok" for row in scans)
    rattle = sum(row["rattle_verdict"] != "ok" for row in scans)
    dishes = sum(row["dish_pixels"] > 0 for row in scans)
    print(f"Audited {len(scans)} kept scans: feedback={feedback}, "
          f"rattle={rattle}, broad-dish candidates={dishes}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
