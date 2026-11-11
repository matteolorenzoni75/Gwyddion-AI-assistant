"""Keep all AFM acquisition channels but do not topography-level other signals."""
from types import SimpleNamespace

from afm_copilot.channels import identify_channel, operation_policy
from afm_copilot.correction_gate import gate_recipe


def test_common_multichannel_signals():
    cases = [
        ("Height", "nm", "height"),
        ("Topography", "m", "height"),
        ("Amplitude", "V", "amplitude"),
        ("Phase", "deg", "phase"),
        ("Amplitude Error", "V", "error"),
        ("Deflection Error", "V", "error"),
        ("Current", "nA", "current"),
        ("KPFM Surface Potential", "V", "potential"),
        ("Frequency Shift", "Hz", "frequency"),
        ("Random Vendor Signal", "V", "unknown"),
    ]
    for name, unit, expected in cases:
        assert identify_channel(name, unit).role == expected, name


def test_conflicting_unit_blocks_height_assumption():
    result = identify_channel("Height", "nA")
    assert result.role == "unknown"
    assert result.confidence == "low"


def test_height_operations_are_not_approved_for_non_height_channels():
    for kind in ("phase", "amplitude", "current", "potential", "unknown"):
        assert operation_policy(kind, "plane_level")["decision"] == "blocked"


def test_gate_recipe_blocks_height_processing_on_phase():
    plan = SimpleNamespace(recipe_key="level-only", rows_are_structure=False,
                           has_terraces=False, needs_despike=False)
    quality = SimpleNamespace(checks=[])
    result = gate_recipe(plan, quality, calibration_verified=True,
                         channel_role="phase")
    assert result["safe_to_execute_full_recipe_without_review"] is False
    assert result["channel_role"] == "phase"
    assert all(op["status"] == "blocked" for op in result["operations"])
    assert result["image_modified"] is False


def test_calibration_unverified_blocks_even_height_recipe():
    plan = SimpleNamespace(recipe_key="level-only", needs_despike=False)
    quality = SimpleNamespace(checks=[])
    result = gate_recipe(plan, quality, calibration_verified=False)
    assert result["safe_to_execute_full_recipe_without_review"] is False
    assert all(op["status"] == "blocked" for op in result["operations"])
