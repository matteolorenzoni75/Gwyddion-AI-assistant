"""Diagnostic safety gate for AFM corrections, not an image processor.

Uses numerical evidence from existing quality and morphology engines.
A recipe is a proposal; risky operations are blocked until reviewed.
No corrected image is produced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from afm_copilot.ops.recipes import get_recipe

# These operations must not run automatically without additional, verified
# evidence. "Smooth-looking" output is not evidence of physical fidelity.
MANUAL_ONLY = frozenset({
    "mark_outliers", "interpolate_under_mask", "polynomial_background",
    "background_around_objects", "plane_around_objects",
})
IRREVERSIBLE_ARTIFACTS = frozenset({
    "saturation", "feedback", "rattle", "settings changed", "interrupted",
})
ROW_OPS = frozenset({"align_rows_median_diff"})


@dataclass(frozen=True)
class Decision:
    operation: str
    status: str
    reason: str

    def to_dict(self):
        return {"operation": self.operation, "status": self.status,
                "reason": self.reason}


def gate_recipe(plan: Any, quality: Any, *, calibration_verified: bool) -> dict:
    """Return operations with safety decisions; no conversion or processing."""
    proposed = getattr(plan, "recipe_key", "level-only")
    recipe = get_recipe(proposed)
    checks = {
        c.name: c for c in getattr(quality, "checks", [])
        if getattr(c, "verdict", "ok") != "ok"
    }
    blocked = []
    decisions = []
    for op in recipe.operations:
        status = "safe_auto"
        reason = "Existing conservative operation; original preserved"
        if not calibration_verified:
            status, reason = "blocked", "Physical XYZ calibration not verified"
        elif op.key in MANUAL_ONLY:
            status, reason = "review", "Requires protected-feature or measurement-loss verification"
        elif op.key in ROW_OPS and getattr(plan, "rows_are_structure", False):
            status, reason = "blocked", "Real scan-row structure could be erased"
        elif op.key in ROW_OPS and (
            getattr(plan, "morphology_restricted", False)
            or getattr(plan, "has_terraces", False)
        ):
            status, reason = "review", "Row alignment may remove true morphology"
        elif op.key == "facet_level" and not getattr(plan, "has_terraces", False):
            status, reason = "blocked", "Facet levelling requires verified terraces"
        elif op.key == "remove_scars" and "glitches" not in checks:
            status, reason = "review", "Scars not confirmed independently of real steps"
        if status in ("blocked", "review"):
            blocked.append(op.key)
        decisions.append(Decision(op.key, status, reason).to_dict())

    warnings = []
    for key in sorted(IRREVERSIBLE_ARTIFACTS & checks.keys()):
        warnings.append({
            "artifact": key, "verdict": checks[key].verdict,
            "action": "flag_not_reconstruct",
        })
    if getattr(plan, "needs_despike", False):
        warnings.append({
            "artifact": "spikes", "verdict": "suspected",
            "action": "review_mask_before_interpolation",
        })
    return {
        "schema_version": 1,
        "proposed_recipe": proposed,
        "calibration_verified": bool(calibration_verified),
        "operations": decisions,
        "review_or_blocked_operations": blocked,
        "artifact_warnings": warnings,
        "safe_to_execute_full_recipe_without_review": not blocked and calibration_verified,
        "image_modified": False,
        "warning": ("Safety assessment only. An operator-approved processor "
                    "must later verify before/after physical metrics."),
    }
