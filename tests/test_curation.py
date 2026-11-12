"""Curation must deduplicate, quarantine disagreement, and disclose no IDs."""
import json

import pytest

from afm_copilot.curation import curation_summary
from afm_copilot.feedback import record_feedback
import afm_copilot.feedback as feedback


@pytest.fixture(autouse=True)
def approved_training_test_root(monkeypatch, tmp_path):
    monkeypatch.setattr(feedback, "TRAINING_ROOT", tmp_path)


def event(scan, store, family="terraces", verdict="confirmed"):
    return record_feedback(
        scan, family=family, effect="advisory", verdict=verdict,
        evidence=["Visible stepped topography"],
        confirmed_training=True, directory=store,
    )


def test_missing_store_is_empty(tmp_path):
    report = curation_summary(tmp_path / "nothing")
    assert report["candidate_scans"] == report["events"] == 0


def test_repeated_confirmation_is_one_candidate(tmp_path):
    scan = tmp_path / "sample.ibw"
    scan.write_bytes(b"data")
    store = tmp_path / "private"
    event(scan, store)
    event(scan, store)
    summary = curation_summary(store)
    assert summary["events"] == 2
    assert summary["unique_scans"] == summary["candidate_scans"] == 1
    assert summary["repeated_confirmations"] == 1
    assert summary["confirmed_families"] == {"terraces": 1}
    assert "sample" not in json.dumps(summary)


def test_disagreeing_confirmations_are_held(tmp_path):
    scan = tmp_path / "sample.ibw"
    scan.write_bytes(b"data")
    store = tmp_path / "private"
    event(scan, store, "terraces")
    event(scan, store, "pores")
    report = curation_summary(store)
    assert report["candidate_scans"] == 0
    assert report["needs_resolution"] == 1


@pytest.mark.parametrize("verdict", ["rejected", "uncertain"])
def test_rejection_or_uncertainty_quarantines_previous_positive(tmp_path, verdict):
    scan = tmp_path / "sample.ibw"
    scan.write_bytes(b"data")
    store = tmp_path / "private"
    event(scan, store)
    event(scan, store, verdict=verdict)
    report = curation_summary(store)
    assert report["candidate_scans"] == 0
    assert report["needs_resolution"] == 1


def test_only_nonpositive_events_are_held(tmp_path):
    scan = tmp_path / "sample.ibw"
    scan.write_bytes(b"data")
    store = tmp_path / "private"
    event(scan, store, verdict="uncertain")
    report = curation_summary(store)
    assert report["candidate_scans"] == 0
    assert report["needs_resolution"] == 1


@pytest.mark.parametrize("bad", [
    "not json",
    '{"scan_id":"x","verdict":"confirmed"}',
    '{"schema_version":2,"scan_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","verdict":"confirmed"}',
])
def test_invalid_feedback_records_fail_closed(tmp_path, bad):
    store = tmp_path / "private"
    store.mkdir()
    (store / "operator_feedback.jsonl").write_text(bad+"\n", encoding="utf-8")
    with pytest.raises(ValueError):
        curation_summary(store)


def test_summary_does_not_export_private_identifiers(tmp_path):
    scan = tmp_path / "Private_perovskite_sample.ibw"
    scan.write_bytes(b"my data")
    store = tmp_path / "private"
    result = event(scan, store)
    summary = json.dumps(curation_summary(store))
    assert result["scan_id"] not in summary
    assert scan.name not in summary
    assert "Visible stepped topography" not in summary
    assert "model_updated" in summary
    assert curation_summary(store)["model_updated"] is False
