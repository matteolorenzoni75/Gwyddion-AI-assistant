"""Mask thresholding and approved Gwyddion handoff regression checks."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from afm_copilot.gwy_io import Channel, load_height, load_mask
from afm_copilot.mask_refinement import propose_mask, robust_plane
import afm_copilot.masked_compare as masked


def synthetic():
    y, x = np.indices((128, 128))
    plane = 1.5e-9 * x / 128 + 2.0e-9 * y / 128
    bump = 15e-9 * np.exp(-((x-63)**2 + (y-64)**2) / (2*8**2))
    return plane + bump


def test_threshold_in_nanometres_marks_only_real_protrusion():
    data = synthetic()
    proposal = propose_mask(data, threshold_nm=2.0, mode="raised")
    assert proposal.safe_for_fit
    assert proposal.mask[64, 63]
    assert not proposal.mask[0, 0]
    assert 0.01 < proposal.masked_fraction < 0.20
    assert proposal.min_unmasked_row_fraction > 0.25


def test_threshold_and_mode_are_operator_adjustable():
    z = synthetic()
    small = propose_mask(z, threshold_nm=1.0, mode="raised")
    large = propose_mask(z, threshold_nm=5.0, mode="raised")
    assert small.masked_fraction > large.masked_fraction
    assert not propose_mask(z, threshold_nm=2, mode="sunken").mask[64, 63]
    with pytest.raises(ValueError):
        propose_mask(z, threshold_nm=0)
    with pytest.raises(ValueError):
        propose_mask(z, threshold_nm=2, mode="guess")


def test_mask_guard_refuses_covering_half_of_surface():
    h = np.zeros((96, 96), dtype=float)
    h[:, 48:] = 30e-9
    proposal = propose_mask(h, threshold_nm=2, mode="both")
    assert not proposal.safe_for_fit


def test_gwyddion_receives_exact_approved_mask_and_keeps_raw(tmp_path, monkeypatch):
    raw = tmp_path / "raw.ibw"
    manual = tmp_path / "manual.gwy"
    raw.write_bytes(b"raw remains unchanged")
    manual.write_bytes(b"manual remains unchanged")
    rows = [{"original": str(raw), "manual": str(manual), "automated": None}]
    manifest = tmp_path / "PRIVATE_pairs.json"
    manifest.write_text(json.dumps({"pairs": rows}), encoding="utf-8")
    mask_root = tmp_path / "private" / "masks"
    monkeypatch.setattr(masked, "MASK_ROOT", mask_root)
    import afm_copilot.masked_compare as mc
    z = synthetic()
    channel = Channel("Height", z, 20e-6, 20e-6)
    mask = propose_mask(z, threshold_nm=2.0, mode="raised").mask
    approved = masked.save_approved_mask(0, raw, mask, threshold_nm=2, mode="raised")
    recorded = []

    class FakeBridge:
        def run_recipe(self, recipe, paths, out_dir):
            assert recipe.steps == ("plane_around_objects", "remove_mask")
            original_input = Path(paths[0])
            assert np.array_equal(load_mask(original_input), mask)
            recorded.append(recipe.steps)
            dest = Path(out_dir) / original_input.name
            shutil.copyfile(original_input, dest)
            return {"results": [{
                "ok": True, "output": str(dest),
                "steps": [
                    {"key": "plane_around_objects", "applied": True},
                    {"key": "remove_mask", "applied": True}],
            }]}

    result = masked.run_masked(
        0, approved, manifest=manifest, output=tmp_path / "auto_output",
        importer=lambda path, work: (channel, {}),
        bridge_factory=FakeBridge,
    )
    assert result["status"] == "generated_for_review"
    assert recorded
    output = json.loads(manifest.read_text())["pairs"][0]["automated"]
    assert Path(output).is_file()
    assert raw.read_bytes() == b"raw remains unchanged"
    assert manual.read_bytes() == b"manual remains unchanged"


def test_unapproved_or_changed_scan_is_rejected(tmp_path, monkeypatch):
    raw = tmp_path / "source.ibw"
    raw.write_bytes(b"first")
    manifest = tmp_path / "pairs.json"
    manifest.write_text(json.dumps({"pairs": [
        {"original": str(raw), "manual": str(tmp_path/"manual.gwy")}
    ]}))
    monkeypatch.setattr(masked, "MASK_ROOT", tmp_path/"private"/"masks")
    approval = masked.save_approved_mask(
        0, raw, np.ones((16,16), dtype=bool),
        threshold_nm=2, mode="raised")
    raw.write_bytes(b"updated raw")
    with pytest.raises(ValueError, match="Original/manual pair not available"):
        masked.run_masked(0, approval, manifest=manifest)


def test_cached_plane_produces_same_mask():
    z = synthetic()
    estimated = robust_plane(z)
    a = propose_mask(z, threshold_nm=2, mode="raised")
    b = propose_mask(z, threshold_nm=2, mode="raised", estimated_plane=estimated)
    assert np.array_equal(a.mask, b.mask)


def test_scar_step_must_be_approved_explicitly(tmp_path, monkeypatch):
    raw = tmp_path / "raw.ibw"
    raw.write_bytes(b"raw instrument bytes")
    manual = tmp_path / "manual.gwy"
    manual.write_bytes(b"manual file")
    manifest = tmp_path / "pairs.json"
    manifest.write_text(json.dumps({"pairs": [
        {"original": str(raw), "manual": str(manual)}
    ]}))
    monkeypatch.setattr(masked, "MASK_ROOT", tmp_path / "private" / "masks")
    z = synthetic()
    mask = propose_mask(z, threshold_nm=2, mode="raised").mask
    approval = masked.save_approved_mask(
        0, raw, mask, threshold_nm=2, mode="raised", remove_scars=True)
    metadata = json.loads(approval.read_text(encoding="utf-8"))
    assert metadata["remove_scars"] is True
    seen = []

    class FakeBridge:
        def run_recipe(self, recipe, paths, out_dir):
            seen.extend(recipe.steps)
            dest = Path(out_dir) / Path(paths[0]).name
            shutil.copyfile(paths[0], dest)
            return {"results": [{
                "ok": True, "output": str(dest),
                "steps": [{"key": key, "applied": True}
                          for key in recipe.steps],
            }]}

    report = masked.run_masked(
        0, approval, manifest=manifest, output=tmp_path / "outputs",
        importer=lambda path, work: (
            Channel("Height", z, 20e-6, 20e-6), {}),
        bridge_factory=FakeBridge)
    assert report["status"] == "generated_for_review"
    assert seen == ["plane_around_objects", "remove_mask", "remove_scars"]
    assert raw.read_bytes() == b"raw instrument bytes"
    assert manual.read_bytes() == b"manual file"
