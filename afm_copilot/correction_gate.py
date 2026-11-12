"""Diagnostic safety gate for AFM corrections, not an image processor.

Uses numerical evidence from existing quality and morphology engines.
A recipe is a proposal; risky operations are blocked until reviewed.
No corrected image is produced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from afm_copilot.ops.catalog import capability_registry, get_operation
from afm_copilot.ops.recipes import Recipe, get_recipe
from afm_copilot.channels import operation_policy

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


def gate_recipe(plan: Any, quality: Any, *, calibration_verified: bool,
                channel_role: str = "height") -> dict:
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
        policy = operation_policy(channel_role, op.key)
        if channel_role != "height":
            status = policy["decision"]
            reason = policy["reason"]
        elif not calibration_verified:
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
        if status not in ("safe_auto",):
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
        "channel_role": channel_role,
        "operations": decisions,
        "review_or_blocked_operations": blocked,
        "artifact_warnings": warnings,
        "safe_to_execute_full_recipe_without_review": (
            not blocked and calibration_verified and channel_role == "height"),
        "image_modified": False,
        "warning": ("Safety assessment only. An operator-approved processor "
                    "must later verify before/after physical metrics."),
    }


# ---------------------------------------------------------------------------
# Iterative planner contract
# ---------------------------------------------------------------------------

MASK_ROLES = frozenset({
    "protect_structure",
    "trusted_background",
    "repair_defect",
    "invalid_or_unknown",
})
MAX_TRIAL_ACTIONS = 8
FAILURE_POLICIES = frozenset({"rollback", "stop", "request_review"})


def planner_contract() -> dict:
    """Machine-readable contract shared by manual/API/local planners.

    This is intentionally provider-neutral. It describes what the planner may
    propose, not what Gwyddion will automatically execute.
    """
    return {
        "schema_version": 1,
        "mask_roles": sorted(MASK_ROLES),
        "max_actions_per_trial": MAX_TRIAL_ACTIONS,
        "failure_policies": sorted(FAILURE_POLICIES),
        "operations": capability_registry(),
        "rules": [
            "Every data-changing step creates a new immutable state.",
            "Reinspect after each data-changing step before proposing another.",
            "A protect_structure mask is never a repair/interpolation mask.",
            "Interpolation/reconstruction requires repair_defect semantics.",
            "Interactive tools and human actions cannot execute headlessly.",
            "Rollback is the default when an expected check fails.",
            "Global RMS reduction is not sufficient evidence of improvement.",
        ],
    }


def validate_iterative_plan(
    plan: dict,
    *,
    calibration_verified: bool = True,
    channel_role: str = "height",
) -> dict:
    """Validate a structured multi-step trial without touching image data.

    The returned state graph is a provenance ledger. It distinguishes measured
    values transformed by levelling from states containing reconstructed pixels.
    """
    if not isinstance(plan, dict):
        raise ValueError("Planner plan must be an object")
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("Planner plan must contain a non-empty actions list")
    if len(actions) > MAX_TRIAL_ACTIONS:
        raise ValueError(
            f"Planner trial exceeds {MAX_TRIAL_ACTIONS} actions")

    source_state = str(plan.get("source_state") or "state-000")
    states = [{
        "state": source_state,
        "parent": None,
        "operation": None,
        "height_provenance": "measured",
        "reconstructed": False,
    }]
    decisions = []
    all_headless = True
    current = source_state

    for index, action in enumerate(actions, 1):
        if not isinstance(action, dict):
            raise ValueError(f"Action {index} must be an object")
        key = str(action.get("operation") or "")
        if not key:
            raise ValueError(f"Action {index} has no operation")
        op = get_operation(key)

        status = "execute"
        reasons = []

        if channel_role != "height":
            status = "blocked"
            reasons.append("Only height/topography may use this planner contract")
        elif not calibration_verified:
            status = "blocked"
            reasons.append("Physical calibration is not verified")

        role = action.get("mask_role")
        if role is not None and role not in MASK_ROLES:
            status = "blocked"
            reasons.append(f"Unknown mask role: {role}")
        if op.required_mask_role and role != op.required_mask_role:
            status = "blocked"
            reasons.append(
                f"{key} requires mask_role={op.required_mask_role}")
        elif op.needs_mask and role is None:
            status = "blocked"
            reasons.append(f"{key} requires an explicit semantic mask role")

        # Structural-protection masks may guide fitting but must never become a
        # repair mask by implication.
        if key == "interpolate_under_mask" and role != "repair_defect":
            status = "blocked"
            reasons.append("Interpolation is permitted only for repair_defect masks")

        if op.execution_mode != "process":
            if status != "blocked":
                status = "review"
            reasons.append(
                f"{key} is {op.execution_mode} and requires operator/GUI input")
        elif not op.executor_ready:
            if status != "blocked":
                status = "review"
            reasons.append(
                f"{key} is known but its deterministic parameter contract "
                "is not verified for headless execution")
        elif op.planner_policy == "manual":
            if status != "blocked":
                status = "review"
            reasons.append(f"{key} is manual-only")
        elif op.planner_policy == "review":
            if status == "execute":
                status = "review"
            reasons.append(f"{key} requires stronger evidence/review")

        failure = str(action.get("on_failure") or "rollback")
        if failure not in FAILURE_POLICIES:
            status = "blocked"
            reasons.append(f"Invalid on_failure policy: {failure}")

        checks = action.get("expected_checks") or []
        if not isinstance(checks, list):
            status = "blocked"
            reasons.append("expected_checks must be a list")
            checks = []
        if op.provenance_effect != "mask_only" and not checks:
            if status == "execute":
                status = "review"
            reasons.append("Data-changing action needs explicit post-checks")

        if op.provenance_effect == "reconstructed_mixed":
            if not bool(action.get("accept_reconstruction")):
                if status == "execute":
                    status = "review"
                reasons.append(
                    "Reconstructed pixels require explicit accept_reconstruction")
            if not action.get("reconstruction_mask_ref"):
                if status == "execute":
                    status = "review"
                reasons.append(
                    "Reconstruction requires a mask reference for provenance")

        out_state = str(action.get("output_state") or f"state-{index:03d}")
        reconstructed = (
            states[-1]["reconstructed"]
            or op.provenance_effect == "reconstructed_mixed"
        )
        states.append({
            "state": out_state,
            "parent": current,
            "operation": key,
            "mask_role": role,
            "height_provenance": (
                "measured_plus_reconstructed" if reconstructed else "measured"
            ),
            "reconstructed": reconstructed,
            "reconstruction_mask_ref": action.get("reconstruction_mask_ref"),
        })
        current = out_state

        if status != "execute":
            all_headless = False
        decisions.append({
            "index": index,
            "operation": key,
            "status": status,
            "reason": "; ".join(reasons) if reasons else "validated",
            "input_state": states[-2]["state"],
            "output_state": out_state,
            "mask_role": role,
            "expected_checks": checks,
            "on_failure": failure,
            "execution_mode": op.execution_mode,
            "provenance_effect": op.provenance_effect,
        })

    stop_conditions = plan.get("stop_conditions") or []
    if not isinstance(stop_conditions, list):
        raise ValueError("stop_conditions must be a list")

    return {
        "schema_version": 1,
        "source_state": source_state,
        "final_state": current,
        "actions": decisions,
        "states": states,
        "stop_conditions": stop_conditions,
        "can_execute_headless": bool(all_headless),
        "requires_review": any(d["status"] == "review" for d in decisions),
        "blocked": any(d["status"] == "blocked" for d in decisions),
        "image_modified": False,
    }


def recipe_from_iterative_plan(plan: dict, *, key: str = "planner-trial") -> Recipe:
    """Create a normal Recipe only when every action is headless and verified.

    This deliberately reuses the existing Gwyddion executor instead of
    introducing a parallel processing path.
    """
    validation = validate_iterative_plan(plan)
    if not validation["can_execute_headless"] or validation["blocked"]:
        reasons = [
            f"{d['operation']}: {d['reason']}"
            for d in validation["actions"] if d["status"] != "execute"
        ]
        raise ValueError("Planner trial is not headless-safe: " + " | ".join(reasons))
    steps = tuple(d["operation"] for d in validation["actions"])
    return Recipe(
        key=key,
        title="Validated planner trial",
        purpose="One bounded iterative trial proposed by the planner.",
        when_to_use="Only after validation of every operation and post-check.",
        when_not_to_use="When any step is interactive, manual, unverified or blocked.",
        steps=steps,
    )
