"""Blind benchmark corpus builder: copies only, hashes every copy."""
import json

import pytest

import afm_copilot.benchmark_corpus as bench
from afm_copilot.benchmark_corpus import build


def _manifest(tmp_path, count=2):
    pairs = []
    sources = tmp_path / "sources"
    sources.mkdir()
    for i in range(count):
        raw = sources / f"sample-{i}.ibw"
        manual = sources / f"sample-{i} corrected.gwy"
        raw.write_bytes(f"raw-{i}".encode())
        manual.write_bytes(f"manual-{i}".encode())
        pairs.append({"original": str(raw), "manual": str(manual)})
    manifest = tmp_path / "private" / "pairs.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"pairs": pairs}), encoding="utf-8")
    return manifest, pairs


def test_builds_neutral_byte_identical_pairs_without_touching_sources(tmp_path):
    manifest, pairs = _manifest(tmp_path)
    destination = tmp_path / "workspace" / "05_Benchmark_Corpus"
    private_map = tmp_path / "private" / "mapping.json"
    before = [(open(p["original"], "rb").read(), open(p["manual"], "rb").read())
              for p in pairs]

    report = build(manifest, destination, private_map)

    assert report["pairs"] == 2
    assert report["files_copied_now"] == 4
    assert report["sha256_verified"] is True
    assert report["source_files_modified"] is False
    assert report["safe_for_external_upload"] is False
    assert (destination / "originals" / "case-001.ibw").read_bytes() == b"raw-0"
    assert (destination / "manual" / "case-001.gwy").read_bytes() == b"manual-0"
    assert [(open(p["original"], "rb").read(), open(p["manual"], "rb").read())
            for p in pairs] == before

    public = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert public["cases"][0]["case"] == "case-001"
    assert "sample-" not in json.dumps(public)

    private = json.loads(private_map.read_text(encoding="utf-8"))
    assert private["cases"][0]["original_source"] == pairs[0]["original"]


def test_rerun_reuses_identical_copies(tmp_path):
    manifest, _ = _manifest(tmp_path, 1)
    destination = tmp_path / "workspace" / "05_Benchmark_Corpus"
    private_map = tmp_path / "private" / "mapping.json"
    build(manifest, destination, private_map)
    report = build(manifest, destination, private_map)
    assert report["files_copied_now"] == 0
    assert report["files_reused_identical"] == 2


def test_refuses_existing_different_content(tmp_path):
    manifest, _ = _manifest(tmp_path, 1)
    destination = tmp_path / "workspace" / "05_Benchmark_Corpus"
    (destination / "originals").mkdir(parents=True)
    (destination / "originals" / "case-001.ibw").write_bytes(b"wrong")
    with pytest.raises(FileExistsError):
        build(manifest, destination, tmp_path / "private" / "mapping.json")


def test_manifest_builder_allows_more_than_64_curated_pairs(tmp_path):
    manifest, _ = _manifest(tmp_path, 65)
    report = build(manifest, tmp_path / "workspace", tmp_path / "private" / "mapping.json")
    assert report["pairs"] == 65


def test_discover_all_corrected_pairs_only_unambiguous_siblings(tmp_path, monkeypatch):
    root = tmp_path / "known"
    root.mkdir()
    (root / "alpha.ibw").write_bytes(b"raw-a")
    (root / "alpha corrected.gwy").write_bytes(b"manual-a")
    (root / "beta corrected.gwy").write_bytes(b"manual-b")
    # Ambiguous: two possible twins reduce to same key.
    (root / "gamma.ibw").write_bytes(b"raw-g1")
    (root / "gamma.gwy").write_bytes(b"raw-g2")
    (root / "gamma corrected.gwy").write_bytes(b"manual-g")

    report = bench.discover_corrected_pairs((root,))
    assert report["summary"]["corrected_tagged"] == 3
    assert report["summary"]["paired"] == 1
    assert report["summary"]["unresolved"] == 2
    assert report["pairs"][0]["original"].endswith("alpha.ibw")
    assert report["pairs"][0]["manual"].endswith("alpha corrected.gwy")
