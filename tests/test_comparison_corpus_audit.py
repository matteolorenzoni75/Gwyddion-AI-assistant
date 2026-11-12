"""Curated comparison audit includes associated and held generated candidates."""
import json
from pathlib import Path

import numpy as np

import afm_copilot.comparison_corpus_audit as auditmod
from afm_copilot.gwy_io import Channel


def test_audit_counts_associated_and_held_candidates(tmp_path, monkeypatch):
    raw1 = tmp_path / "raw1.ibw"
    raw2 = tmp_path / "raw2.ibw"
    man1 = tmp_path / "manual1.gwy"
    man2 = tmp_path / "manual2.gwy"
    auto1 = tmp_path / "auto1.gwy"
    for p in (raw1, raw2, man1, man2, auto1):
        p.write_bytes(b"x")

    output = tmp_path / "out"
    held = output / auditmod._id(raw2) / "corrected" / "height.gwy"
    held.parent.mkdir(parents=True)
    held.write_bytes(b"held")

    manifest = tmp_path / "pairs.json"
    manifest.write_text(json.dumps({"pairs": [
        {"original": str(raw1), "manual": str(man1), "automated": str(auto1)},
        {"original": str(raw2), "manual": str(man2), "automated": None},
    ]}), encoding="utf-8")

    channels = {
        str(raw1.resolve()): Channel("Height", np.zeros((8, 8)), 1e-6, 1e-6),
        str(raw2.resolve()): Channel("Height", np.ones((8, 8))*1e-9, 1e-6, 1e-6),
        str(man1.resolve()): Channel("Height", np.zeros((8, 8)), 1e-6, 1e-6),
        str(man2.resolve()): Channel("Height", np.ones((8, 8))*1.2e-9, 1e-6, 1e-6),
        str(auto1.resolve()): Channel("Height", np.zeros((8, 8)), 1e-6, 1e-6),
        str(held.resolve()): Channel("Height", np.ones((8, 8))*2e-9, 1e-6, 1e-6),
    }
    monkeypatch.setattr(
        auditmod, "_load_any",
        lambda path, scratch: channels[str(Path(path).resolve())])

    report = auditmod.audit(manifest, output)
    assert report["summary"]["pairs"] == 2
    assert report["summary"]["states"] == {
        "associated_automatic": 1,
        "held_generated_candidate": 1,
    }
    assert report["summary"]["held_generated_candidates"] == 1
    assert report["summary"]["manual_auto_comparable"] == 2
    assert report["summary"]["source_files_modified"] is False
    assert report["pairs"][1]["associated"] is False
    assert Path(report["pairs"][1]["automatic"]) == held


def test_private_save_does_not_modify_source_manifest(tmp_path):
    source = tmp_path / "manifest.json"
    source.write_text('{"pairs":[]}', encoding="utf-8")
    report = {"summary": {"pairs": 0}, "pairs": []}
    out = tmp_path / "private" / "audit.json"
    auditmod.save_private(report, out)
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["pairs"] == 0
    assert source.read_text(encoding="utf-8") == '{"pairs":[]}'
