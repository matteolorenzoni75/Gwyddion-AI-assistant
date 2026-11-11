"""Local manual correction search preserves files and never exposes filenames."""
from pathlib import Path

from afm_copilot.manual_pairs import _key, scan_folder, inventory, save_private


def test_existing_operator_corrected_naming_is_recognized(tmp_path):
    folder = tmp_path / "sample"
    folder.mkdir()
    (folder / "scan.ibw").write_bytes(b"raw")
    (folder / "scan.ibw corrected with facet level").write_bytes(b"operator")
    (folder / "scan processed.gwy").write_bytes(b"auto")
    report = scan_folder(tmp_path)
    assert report["candidates"] == 1
    assert len(report["pairs"]) == 1
    assert Path(report["pairs"][0]["original"]).name == "scan.ibw"
    assert Path(report["pairs"][0]["manual"]).name == "scan.ibw corrected with facet level"
    assert Path(report["pairs"][0]["automated"]).name == "scan processed.gwy"
    assert (folder / "scan.ibw").read_bytes() == b"raw"


def test_ambiguous_originals_are_not_assumed_to_match(tmp_path):
    folder = tmp_path / "scan"
    folder.mkdir()
    (folder / "a.ibw").write_bytes(b"a")
    (folder / "a.tiff").write_bytes(b"b")
    (folder / "a corrected.gwy").write_bytes(b"target")
    report = scan_folder(tmp_path)
    assert report["candidates"] == 1
    assert len(report["pairs"]) == 0


def test_different_directory_same_basename_not_merged(tmp_path):
    for dirname in ("first", "second"):
        path = tmp_path / dirname
        path.mkdir()
        (path / "same.ibw").write_bytes(dirname.encode())
    (tmp_path / "second" / "same corrected.gwy").write_bytes(b"manual")
    result = scan_folder(tmp_path)
    assert len(result["pairs"]) == 1
    assert "second" in result["pairs"][0]["original"]


def test_empty_folder_and_report_are_safe(tmp_path):
    result = inventory([tmp_path / "missing"])
    assert result["summary"]["directories_searched"] == 0
    path = save_private(result, tmp_path / "private" / "PRIVATE_pairs.json")
    assert path.exists()
    assert not (tmp_path / "missing").exists()


def test_key_ignores_operator_suffix_not_other_meaning():
    assert _key(Path("scan.ibw corrected with facet")) == "scan"
    assert _key(Path("scan processed.gwy")) == "scan"
    assert _key(Path("scan.ibw")) == "scan"
