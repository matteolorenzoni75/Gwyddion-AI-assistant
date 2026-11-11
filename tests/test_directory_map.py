"""AFM workspace inventory never moves or deletes the original scans."""
from pathlib import Path

import pytest

from afm_copilot.directory_map import build_map, prepare_workspace


def test_directory_map_only_checks_known_paths(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "original.ibw").write_bytes(b"original")
    original = tmp_path / "source.ibw"
    original.write_bytes(b"raw")
    manual = tmp_path / "source corrected.gwy"
    manual.write_bytes(b"corrected")
    result = build_map(
        entries=[("archive", "AFM archive", archive, "original data"),
                 ("missing", "Output", tmp_path / "missing", "generated only")],
        pairs=[{"original": str(original), "manual": str(manual),
                "automated": None}],
    )
    assert result["summary"]["known_locations"] == 2
    assert result["summary"]["existing_locations"] == 1
    assert result["summary"]["manual_pairs_recorded"] == 1
    assert result["summary"]["manual_folders"] == 1
    assert result["summary"]["original_images_missing"] == 0
    assert result["summary"]["automatic_results_associated"] == 0
    assert result["summary"]["full_archive_rescanned"] is False
    assert original.read_bytes() == b"raw"
    assert (archive / "original.ibw").read_bytes() == b"original"


def test_prepare_workspace_creates_only_empty_directories(tmp_path):
    root = tmp_path / "workspace"
    result = prepare_workspace(root)
    assert result["folders_created"] == 4
    assert result["source_files_moved"] == 0
    assert result["source_files_deleted"] == 0
    assert sorted(p.name for p in root.iterdir()) == [
        "01_Manual_To_Review", "02_Automatic_Results",
        "03_Approved", "04_Reports"
    ]
    again = prepare_workspace(root)
    assert again["folders_created"] == 0
    assert again["folders_total"] == 4


def test_prepare_workspace_never_accepts_git_checkout():
    from afm_copilot.feedback import PROJECT_ROOT
    with pytest.raises(ValueError):
        prepare_workspace(PROJECT_ROOT)
