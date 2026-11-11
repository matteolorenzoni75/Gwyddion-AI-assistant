"""Safety decisions explain proposed AFM clean-up without altering data."""
from types import SimpleNamespace

from afm_copilot.correction_gate import gate_recipe


def _plan(recipe="quick-clean", **kwargs):
    return SimpleNamespace(recipe_key=recipe, has_terraces=False,
                           morphology_restricted=False,
                           rows_are_structure=False, needs_despike=False,
                           **kwargs)


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
