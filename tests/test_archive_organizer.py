"""Archive moves are explicit, local, recoverable, non-deduplicating."""
import json
from pathlib import Path

import pytest

from afm_copilot.archive_organizer import (
    build_plan, execute_plan, save_plan,
)


def _sample(tmp_path):
    root = tmp_path / "All AFM Data"
    root.mkdir()
    (root / "sample1").mkdir()
    (root / "sample2").mkdir()
    one = root / "sample1" / "same.ibw"
    two = root / "sample2" / "same.ibw"
    one.write_bytes(b"abc")
    two.write_bytes(b"abc")
    (root / "sample2" / "metadata.txt").write_text("sidecar", encoding="utf-8")
    return root, one, two


def test_preview_detects_identical_repeated_files_without_move(tmp_path):
    root, one, two = _sample(tmp_path)
    result = build_plan(root)
    assert result["summary"]["total_files"] == 3
    assert result["summary"]["afm_scans"] == 2
    assert result["summary"]["exact_duplicate_groups"] == 1
    assert result["summary"]["exact_duplicate_extra_copies"] == 1
    assert result["summary"]["files_to_move"] == 3
    assert one.read_bytes() == two.read_bytes() == b"abc"
    targets = [r["destination"].casefold() for r in result["entries"]]
    assert len(set(targets)) == 3
    assert all(Path(x).parent == root for x in targets)


def test_explicit_execute_flattens_and_only_removes_empty_subdirs(tmp_path):
    root, one, two = _sample(tmp_path)
    plan = build_plan(root)
    priv = tmp_path / "PRIVATE" / "plan.json"
    save_plan(plan, priv)
    journal = tmp_path / "PRIVATE" / "journal.jsonl"
    report = execute_plan(plan, expected_root=root, journal=journal)
    assert report["moved"] == 3
    assert report["blocked_or_changed"] == 0
    assert report["empty_subdirectories_removed"] == 2
    assert not one.exists()
    assert not two.exists()
    assert sorted(x.suffix for x in root.iterdir()) == [".ibw", ".ibw", ".txt"]
    assert sorted(x.read_bytes() for x in root.iterdir()) == [
        b"abc", b"abc", b"sidecar"]
    assert len(journal.read_text().splitlines()) == 3
    again = execute_plan(plan, expected_root=root, journal=journal)
    assert again["moved"] == 0
    assert again["already_moved"] == 3


def test_changed_file_cannot_be_moved(tmp_path):
    root, one, _ = _sample(tmp_path)
    plan = build_plan(root)
    one.write_bytes(b"new bytes")
    report = execute_plan(plan, expected_root=root,
                          journal=tmp_path / "private" / "journal.jsonl")
    assert report["blocked_or_changed"] >= 1
    assert one.read_bytes() == b"new bytes"


def test_existing_destination_is_never_overwritten(tmp_path):
    root, one, _ = _sample(tmp_path)
    plan = build_plan(root)
    row = next(r for r in plan["entries"] if r["source"] == str(one))
    Path(row["destination"]).write_bytes(b"another file")
    report = execute_plan(plan, expected_root=root,
                          journal=tmp_path / "private" / "journal.jsonl")
    assert report["blocked_or_changed"] >= 1
    assert one.exists()
    assert Path(row["destination"]).read_bytes() == b"another file"


def test_private_report_must_stay_outside_source_tree(tmp_path):
    root, *_ = _sample(tmp_path)
    with pytest.raises(ValueError, match="outside source"):
        save_plan(build_plan(root), root / "PRIVATE_plan.json")


def test_preview_does_not_report_names_or_paths(tmp_path):
    root, *_ = _sample(tmp_path)
    summary = json.dumps(build_plan(root)["summary"])
    assert "sample1" not in summary
    assert "All AFM Data" not in summary
    assert "same.ibw" not in summary
