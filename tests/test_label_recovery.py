"""Locate saved expert labels without disclosing them or changing any files."""
import json
import sqlite3

from afm_copilot.labeling import register_folder, save_label
from tools.find_saved_labels import locate


def test_find_legacy_review_and_other_label_db(tmp_path):
    files = tmp_path / "raw"
    files.mkdir()
    (files / "scan.ibw").write_bytes(b"scan")
    store = tmp_path / "private" / "labels.sqlite3"
    register_folder(files, store)
    with sqlite3.connect(store) as conn:
        scan_id = conn.execute("SELECT scan_id FROM scans").fetchone()[0]
    save_label(scan_id, family="terraces", artifacts=[], quality="usable",
               confidence=5, sample_group="specimen-1", dataset_role="train",
               notes="Private topography details", db_path=store)
    review = files / ".afm-copilot-reviews.json"
    review.write_text(json.dumps({"reviews": [{
        "scan": "confidential_sample", "family": "pores", "effect": "advisory",
        "evidence": ["Private substrate description"]
    }]}), encoding="utf-8")
    report = tmp_path / "private" / "recovery" / "PRIVATE_locations.json"
    result = locate([tmp_path], private_report=report)
    assert result["review_entries"] == 1
    assert result["database_labels"] == 1
    assert result["sources_found"] == 2
    assert report.exists()
    visible = json.dumps(result)
    assert "confidential" not in visible.lower()
    assert "specimen-1" not in visible
    assert str(tmp_path) not in visible
    assert "Private substrate" not in visible


def test_bad_review_fails_safe_and_does_not_stop_search(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / ".afm-copilot-reviews.json").write_text("{bad", encoding="utf-8")
    result = locate([folder], private_report=tmp_path / "private_report.json")
    assert result["sources_found"] == 1
    assert result["review_entries"] == 0
    assert result["source_counts"][0]["status"] == "unreadable"
    assert result["no_labels_modified"]
