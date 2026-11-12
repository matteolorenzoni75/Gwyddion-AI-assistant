"""Offline correction workflow: no raw rewrites or automatic approvals."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from afm_copilot.auto_compare import (
    _calibrated, _id, process_one, run_batch,
)


def test_bad_calibration_is_held_before_gwyddion_recipe(tmp_path):
    original = tmp_path / "raw.ibw"
    manual = tmp_path / "raw corrected.gwy"
    original.write_bytes(b"original")
    manual.write_bytes(b"manual")
    bad = SimpleNamespace(
        z_unit="V", xy_unit="m", xreal=1e-6, yreal=1e-6,
        xres=64, yres=64, data=np.ones((64, 64)))
    def importer(path, work):
        return bad, {}
    result = process_one(
        {"original": str(original), "manual": str(manual)},
        output=tmp_path.parent / "auto_output",
        scratch=tmp_path.parent / "scratch",
        importer=importer,
        bridge_factory=lambda: (_ for _ in ()).throw(
            AssertionError("must not run the bridge")))
    assert result["state"] == "held_calibration"
    assert original.read_bytes() == b"original"
    assert manual.read_bytes() == b"manual"


def test_output_never_goes_inside_original_folder(tmp_path):
    original = tmp_path / "raw.ibw"
    manual = tmp_path / "manual.gwy"
    original.write_bytes(b"raw")
    manual.write_bytes(b"manual")
    def importer(*args):
        raise AssertionError("must not import when output unsafe")
    state = process_one(
        {"original": str(original), "manual": str(manual)},
        output=tmp_path / "processed",
        importer=importer)
    assert state["state"] == "held_output_inside_source"


def test_generated_manifest_is_private_and_resumable(tmp_path):
    original = tmp_path / "raw.ibw"
    manual = tmp_path / "raw corrected.gwy"
    original.write_bytes(b"raw")
    manual.write_bytes(b"human")
    manifest = tmp_path / "PRIVATE_pairs.json"
    manifest.write_text(json.dumps({"pairs": [
        {"original": str(original), "manual": str(manual), "automated": None}
    ]}), encoding="utf-8")
    result_path = tmp_path.parent / "output" / "derived.gwy"
    def fake(row, **kwargs):
        row["automated"] = str(result_path)
        return {"state": "generated_for_review", "automated": str(result_path)}
    report = run_batch(manifest, output=tmp_path.parent / "output",
                       processor=fake)
    assert report["new_auto_associations"] == 1
    assert report["automatic_approval"] is False
    assert report["source_scans_modified"] is False
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["pairs"][0]["automated"] == str(result_path)
    assert original.read_bytes() == b"raw"
    assert manual.read_bytes() == b"human"


def test_batch_allows_current_17_pair_corpus(tmp_path):
    manifest = tmp_path / "PRIVATE_pairs.json"
    manifest.write_text(json.dumps({
        "pairs": [{"original": f"raw-{i}.ibw", "manual": f"corrected-{i}.gwy"}
                  for i in range(17)]
    }))
    report = run_batch(
        manifest, output=tmp_path.parent / "output",
        processor=lambda row, **kwargs: {"state": "held_missing_input"})
    assert report["pairs_examined"] == 17
    assert report["states"] == {"held_missing_input": 17}


def test_batch_refuses_unbounded_manifest(tmp_path):
    manifest = tmp_path / "PRIVATE_pairs.json"
    manifest.write_text(json.dumps({
        "pairs": [{"original": f"raw-{i}.ibw", "manual": f"corrected-{i}.gwy"}
                  for i in range(65)]
    }))
    import pytest
    with pytest.raises(ValueError, match="64"):
        run_batch(manifest, output=tmp_path.parent / "output")


def test_image_identity_includes_source_content_metadata(tmp_path):
    raw = tmp_path / "raw.ibw"
    raw.write_bytes(b"first")
    first = _id(raw)
    raw.write_bytes(b"different-size-content")
    assert _id(raw) != first


def test_existing_automatic_association_is_not_reprocessed(tmp_path):
    existing = tmp_path / "already.gwy"
    existing.write_bytes(b"existing automatic")
    raw = tmp_path / "raw.ibw"
    manual = tmp_path / "manual.gwy"
    raw.write_bytes(b"raw")
    manual.write_bytes(b"manual")
    result = process_one({
        "original": str(raw), "manual": str(manual), "automated": str(existing)
    }, output=tmp_path.parent / "output",
       importer=lambda *args: (_ for _ in ()).throw(
           AssertionError("existing automatic must be skipped")))
    assert result["state"] == "existing"
    assert existing.read_bytes() == b"existing automatic"
