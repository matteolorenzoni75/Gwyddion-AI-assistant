"""Training evidence must remain private, explicit and separate from holdouts."""
import json

import pytest

from afm_copilot.feedback import feedback_counts, record_feedback
import afm_copilot.feedback as feedback


@pytest.fixture(autouse=True)
def approved_training_test_root(monkeypatch, tmp_path):
    # Test fixtures only; production uses a separate approved training folder.
    monkeypatch.setattr(feedback, "TRAINING_ROOT", tmp_path)


def record(path, store, **opts):
    return record_feedback(path, family="granular_continuous", effect="restrict",
                           verdict="confirmed", evidence=["Continuous texture"],
                           confirmed_training=True, directory=store, **opts)


def test_append_only_anonymous_confirmed_feedback(tmp_path):
    source = tmp_path / "Confidential_Sample_42.ibw"
    source.write_bytes(b"igor data")
    store = tmp_path / "private_store"
    one = record(source, store)
    two = record(source, store)
    assert one["scan_id"] == two["scan_id"]
    lines = (store / "operator_feedback.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert "Confidential_Sample_42" not in "\n".join(lines)
    assert str(source) not in "\n".join(lines)
    assert json.loads(lines[0])["model_updated"] is False
    assert feedback_counts(store)["confirmed"] == 2


def test_changed_file_is_new_identity(tmp_path):
    scan = tmp_path / "image.ibw"
    scan.write_bytes(b"first")
    initial = record(scan, tmp_path / "private")
    scan.write_bytes(b"changed")
    second = record(scan, tmp_path / "private")
    assert initial["scan_id"] != second["scan_id"]


def test_requires_explicit_confirmation(tmp_path):
    scan = tmp_path / "scan.ibw"
    scan.write_bytes(b"scan")
    with pytest.raises(ValueError, match="explicitly"):
        record_feedback(scan, family="terraces", effect="advisory",
                        verdict="confirmed", evidence=["Step"],
                        directory=tmp_path / "private")


def test_blind_scan_is_never_trainable(tmp_path):
    directory = tmp_path / "blind_test"
    directory.mkdir()
    scan = directory / "scan.ibw"
    scan.write_bytes(b"scan")
    with pytest.raises(ValueError, match="Blind/test"):
        record(scan, tmp_path / "private")
    same_name = tmp_path / "scan-053.gwy"
    same_name.write_bytes(b"raw")
    with pytest.raises(ValueError, match="Blind/test"):
        record(same_name, tmp_path / "private")


def test_no_uncertain_positive_label(tmp_path):
    scan = tmp_path / "a.ibw"
    scan.write_bytes(b"scan")
    with pytest.raises(ValueError, match="definite"):
        record_feedback(scan, family="uncertain", effect="advisory",
                        verdict="confirmed", evidence=["unknown"],
                        confirmed_training=True, directory=tmp_path / "private")


def test_rejection_stored_but_not_used_as_ground_truth(tmp_path):
    scan = tmp_path / "a.ibw"
    scan.write_bytes(b"scan")
    record_feedback(scan, family="terraces", effect="advisory",
                    verdict="rejected", evidence=["not terraces"],
                    confirmed_training=True, directory=tmp_path / "private")
    entry = json.loads((tmp_path / "private" / "operator_feedback.jsonl").read_text())
    assert entry["validated_label"] is None
    assert entry["training_eligible"] is False
    assert feedback_counts(tmp_path / "private")["rejected"] == 1


def test_private_store_cannot_be_in_checkout(tmp_path):
    from afm_copilot.feedback import PROJECT_ROOT
    scan = tmp_path / "a.ibw"
    scan.write_bytes(b"scan")
    with pytest.raises(ValueError, match="outside the Git checkout"):
        record(scan, PROJECT_ROOT / "tmp_private_training")


def test_empty_evidence_refused_for_confirmed(tmp_path):
    scan = tmp_path / "a.ibw"
    scan.write_bytes(b"scan")
    with pytest.raises(ValueError, match="evidence"):
        record_feedback(scan, family="terraces", effect="advisory",
                        verdict="confirmed", evidence=[],
                        confirmed_training=True, directory=tmp_path / "private")


def test_blind_test_folder_with_spaces_is_not_trainable(tmp_path):
    folder = tmp_path / "Blind test small set"
    folder.mkdir()
    path = folder / "a.tiff"
    path.write_bytes(b"data")
    with pytest.raises(ValueError, match="Blind/test"):
        record(path, tmp_path / "private")


def test_private_index_keeps_original_path_only_locally(tmp_path):
    scan = tmp_path / "Private_sample_42.ibw"
    scan.write_bytes(b"instrument data")
    store = tmp_path / "private"
    info = record(scan, store)
    paths = [json.loads(x) for x in
             (store / "private_source_index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert paths[0]["path"] == str(scan.resolve())
    assert paths[0]["scan_id"] == info["scan_id"]
    assert paths[0]["file_size"] == scan.stat().st_size
    assert str(scan) not in (store / "operator_feedback.jsonl").read_text(encoding="utf-8")


def test_declared_raw_test_corpus_is_excluded_even_if_training_root_overlaps(
        tmp_path, monkeypatch):
    folder = tmp_path / "OLD input IMAGES"
    folder.mkdir()
    scan = folder / "s001.IBW"
    scan.write_bytes(b"test corpus data")
    monkeypatch.setattr(feedback, "TEST_CORPUS_ROOT", folder)
    with pytest.raises(ValueError, match="Blind/test"):
        record(scan, tmp_path / "private")


def test_scans_outside_approved_training_root_are_rejected(tmp_path, monkeypatch):
    scan = tmp_path / "unapproved.ibw"
    scan.write_bytes(b"raw")
    approved = tmp_path / "approved"
    approved.mkdir()
    monkeypatch.setattr(feedback, "TRAINING_ROOT", approved)
    with pytest.raises(ValueError, match="outside the dedicated training"):
        record(scan, tmp_path / "private")
