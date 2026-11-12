"""Operator labeling is private, incremental and safe across dataset splits."""
from pathlib import Path

import pytest

from afm_copilot.labeling import (counts, discover, get_scans, register_folder,
                                 save_label, safe_summary)


def make_data(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    (root / "some_scan.IBW").write_bytes(b"raw a")
    (root / "sub").mkdir()
    (root / "sub" / "some_other.TIFF").write_bytes(b"raw b")
    (root / "sub" / "ignore.png").write_bytes(b"not AFM")
    db = tmp_path / "private" / "label.sqlite3"
    return root, db


def label(row, db, *, family="terraces", group="specimen-A",
          role="train", metrics=None):
    return save_label(
        row["scan_id"], family=family, artifacts=["tilt", "spikes"],
        quality="usable", confidence=4, sample_group=group, dataset_role=role,
        notes="Visible stepped morphology", metrics=metrics, db_path=db,
    )


def test_recursive_idempotent_add_and_retain_existing_labels(tmp_path):
    folder, db = make_data(tmp_path)
    assert len(discover(folder)) == 2
    assert register_folder(folder, db) == {"found": 2, "added": 2, "total": 2}
    first = get_scans(db)[0]
    label(first, db)
    again = register_folder(folder, db)
    assert again["added"] == 0
    assert get_scans(db)[0]["family"] == "terraces"


def test_saved_features_and_artifacts_are_restored(tmp_path):
    folder, db = make_data(tmp_path)
    register_folder(folder, db)
    row = get_scans(db)[0]
    label(row, db, metrics={"rms_raw_m": 1e-9, "row_banding": 0.4})
    saved = get_scans(db)[0]
    assert saved["metrics"]["rms_raw_m"] == 1e-9
    assert saved["artifacts"] == ["spikes", "tilt"]
    assert saved["notes"] == "Visible stepped morphology"
    assert saved["quality"] == "usable"


def test_two_scans_from_same_group_cannot_use_different_splits(tmp_path):
    folder, db = make_data(tmp_path)
    register_folder(folder, db)
    first, second = get_scans(db)
    label(first, db, group="same specimen", role="train")
    with pytest.raises(ValueError, match="Same specimen/session"):
        label(second, db, group="same specimen", role="holdout")


def test_byte_identical_files_cannot_cross_splits(tmp_path):
    folder, db = make_data(tmp_path)
    duplicate = folder / "copy-of-first.ibw"
    duplicate.write_bytes((folder / "some_scan.IBW").read_bytes())
    register_folder(folder, db)
    rows = get_scans(db)
    first = next(r for r in rows if Path(r["path"]).name == "some_scan.IBW")
    second = next(r for r in rows if Path(r["path"]).name == "copy-of-first.ibw")
    label(first, db, group="A", role="train")
    with pytest.raises(ValueError, match="Identical image bytes"):
        label(second, db, group="B", role="validation")


def test_uncertain_class_is_not_training_truth(tmp_path):
    folder, db = make_data(tmp_path)
    register_folder(folder, db)
    with pytest.raises(ValueError, match="Uncertain"):
        label(get_scans(db)[0], db, family="uncertain", role="train")


def test_labeled_file_changes_are_detected(tmp_path):
    folder, db = make_data(tmp_path)
    register_folder(folder, db)
    first = get_scans(db)[0]
    label(first, db)
    Path(first["path"]).write_bytes(b"changed scan data")
    with pytest.raises(ValueError, match="Source bytes have changed"):
        label(first, db)


def test_aggregates_have_no_names_paths_or_notes(tmp_path):
    folder, db = make_data(tmp_path)
    register_folder(folder, db)
    label(get_scans(db)[0], db)
    summary = safe_summary(db)
    assert summary["total"] == 2
    assert summary["labeled"] == 1
    assert summary["roles"]["train"] == 1
    text = str(summary)
    assert str(folder) not in text
    assert "some_scan" not in text
    assert "Visible stepped morphology" not in text


def test_training_split_requires_group(tmp_path):
    folder, db = make_data(tmp_path)
    register_folder(folder, db)
    with pytest.raises(ValueError, match="Sample/group ID"):
        label(get_scans(db)[0], db, group="", role="validation")


def test_db_cannot_be_inside_public_project(tmp_path):
    from afm_copilot.labeling import PROJECT_ROOT
    folder, _db = make_data(tmp_path)
    with pytest.raises(ValueError, match="outside the public Git checkout"):
        register_folder(folder, PROJECT_ROOT / "temp_labeling.db")


def test_blank_morphology_is_not_saved_as_an_expert_label(tmp_path):
    folder, db = make_data(tmp_path)
    register_folder(folder, db)
    with pytest.raises(ValueError, match="Choose a morphology"):
        label(get_scans(db)[0], db, family="unclassified", role="unassigned")
    assert counts(db)["labeled"] == 0
