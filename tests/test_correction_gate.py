"""Safety decisions explain proposed AFM clean-up without altering data."""
from types import SimpleNamespace

from afm_copilot.correction_gate import (
    gate_recipe, planner_contract, recipe_from_iterative_plan,
    validate_iterative_plan,
)


def _plan(recipe="quick-clean", **kwargs):
    values = dict(recipe_key=recipe, has_terraces=False,
                  morphology_restricted=False, rows_are_structure=False,
                  needs_despike=False)
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_row_structure_vetoes_row_alignment():
    plan = _plan(rows_are_structure=True)
    q = SimpleNamespace(checks=[])
    result = gate_recipe(plan, q, calibration_verified=True)
    alignment = next(x for x in result["operations"]
                     if x["operation"] == "align_rows_median_diff")
    assert alignment["status"] == "blocked"
    assert result["safe_to_execute_full_recipe_without_review"] is False


def test_object_background_fit_requires_review():
    q = SimpleNamespace(checks=[])
    result = gate_recipe(_plan("isolate-objects-flat"), q,
                         calibration_verified=True)
    assert any(x["status"] == "review" for x in result["operations"])
    assert result["image_modified"] is False


def test_feedback_diagnostics_are_flagged_not_reconstructed():
    q = SimpleNamespace(checks=[
        SimpleNamespace(name="feedback", verdict="fixable"),
        SimpleNamespace(name="rattle", verdict="fixable")])
    result = gate_recipe(_plan("level-only"), q,
                         calibration_verified=True)
    assert {item["artifact"] for item in result["artifact_warnings"]} == {
        "feedback", "rattle"}
    assert all(item["action"] == "flag_not_reconstruct"
               for item in result["artifact_warnings"])



def test_contract_exposes_interactive_path_level_and_human_mask_edit():
    contract = planner_contract()
    operations = {item["key"]: item for item in contract["operations"]}
    assert operations["path_level"]["execution_mode"] == "interactive_tool"
    assert operations["path_level"]["executor_ready"] is False
    assert operations["manual_mask_edit"]["execution_mode"] == "human"
    assert operations["interpolate_under_mask"]["required_mask_role"] == "repair_defect"


def test_interpolation_cannot_reuse_structure_protection_mask():
    result = validate_iterative_plan({
        "actions": [{
            "operation": "interpolate_under_mask",
            "mask_role": "protect_structure",
            "accept_reconstruction": True,
            "reconstruction_mask_ref": "mask-1",
            "expected_checks": ["repair region bounded"],
        }],
    })
    assert result["blocked"] is True
    assert result["can_execute_headless"] is False
    assert "repair_defect" in result["actions"][0]["reason"]


def test_reconstruction_is_recorded_in_state_provenance():
    result = validate_iterative_plan({
        "actions": [{
            "operation": "interpolate_under_mask",
            "mask_role": "repair_defect",
            "accept_reconstruction": True,
            "reconstruction_mask_ref": "mask-repair-7",
            "expected_checks": ["feature edges outside mask unchanged"],
        }],
    })
    # It still requires review by policy, but the provenance ledger must be
    # correct before any later operator approval/execution can occur.
    assert result["states"][-1]["reconstructed"] is True
    assert result["states"][-1]["height_provenance"] == "measured_plus_reconstructed"
    assert result["states"][-1]["reconstruction_mask_ref"] == "mask-repair-7"


def test_path_level_is_a_plannable_review_step_not_headless_execution():
    result = validate_iterative_plan({
        "actions": [{
            "operation": "path_level",
            "expected_checks": ["selected background paths agree after levelling"],
            "on_failure": "rollback",
        }],
    })
    assert result["blocked"] is False
    assert result["requires_review"] is True
    assert result["can_execute_headless"] is False
    assert result["actions"][0]["execution_mode"] == "interactive_tool"


def test_simple_validated_trial_reuses_existing_recipe_executor():
    plan = {
        "actions": [
            {
                "operation": "plane_level",
                "expected_checks": ["residual global tilt decreases"],
            },
            {
                "operation": "zero_mean",
                "expected_checks": ["mean is zero without geometry change"],
            },
        ],
        "stop_conditions": ["no further defensible artifact reduction"],
    }
    validation = validate_iterative_plan(plan)
    assert validation["can_execute_headless"] is True
    assert [s["parent"] for s in validation["states"][1:]] == [
        "state-000", "state-001"]
    recipe = recipe_from_iterative_plan(plan)
    assert recipe.steps == ("plane_level", "zero_mean")
    assert [item["gwy_func"] for item in recipe.to_job()] == ["level", "zero_mean"]
