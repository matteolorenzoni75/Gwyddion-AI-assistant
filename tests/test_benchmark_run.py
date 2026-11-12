"""Blind benchmark runner/export keeps external input separate from references."""
import json
from pathlib import Path

import numpy as np

import afm_copilot.benchmark_run as br
from afm_copilot.gwy_io import Channel, load_height, save_height


def _case_root(tmp_path):
    root = tmp_path / "bench"
    (root / "originals").mkdir(parents=True)
    (root / "manual").mkdir()
    (root / "copilot").mkdir()
    raw = root / "originals" / "case-001.gwy"
    manual = root / "manual" / "case-001.gwy"
    save_height(Channel("Height", np.arange(64, dtype=float).reshape(8, 8) * 1e-9,
                        1e-6, 1e-6), raw)
    save_height(Channel("Height", np.ones((8, 8))*2e-9, 1e-6, 1e-6), manual)
    (root / "manifest.json").write_text(json.dumps({"cases": [{
        "case": "case-001",
        "original": "originals/case-001.gwy",
        "manual": "manual/case-001.gwy",
    }]}), encoding="utf-8")
    return root, raw, manual


def test_prepare_share_separates_blind_from_manual(tmp_path, monkeypatch):
    root, raw, manual = _case_root(tmp_path)
    monkeypatch.setattr(br, "BLIND", root / "share" / "blind_inputs")
    monkeypatch.setattr(br, "REFERENCE", root / "share" / "reference")
    monkeypatch.setattr(br, "RUN_MANIFEST", root / "benchmark_auto_manifest.json")

    report = br.prepare_share(root)

    assert report["blind_inputs_sanitized"] == 1
    assert report["manual_references_sanitized"] == 1
    assert report["upload_blind_first"] is True
    assert (root / "share" / "blind_inputs" / "case-001.gwy").is_file()
    assert not (root / "share" / "blind_inputs" / "case-001-manual.gwy").exists()
    assert (root / "share" / "reference" / "case-001-manual.gwy").is_file()
    blind = load_height(root / "share" / "blind_inputs" / "case-001.gwy")
    assert blind.name == "Height"
    assert blind.meta == {}


def test_run_copilot_uses_benchmark_copies_and_records_state(tmp_path, monkeypatch):
    root, raw, manual = _case_root(tmp_path)
    monkeypatch.setattr(br, "RUN_MANIFEST", root / "benchmark_auto_manifest.json")
    seen = []

    def fake_process(row, *, output, scratch):
        seen.append((row["original"], row["manual"], str(output)))
        out = Path(output) / "fake" / "corrected" / "height.gwy"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"x")
        row["automated"] = str(out)
        return {"state": "generated_for_review", "recipe": "level-only",
                "steps_applied": ["level"], "source_rms_nm": 1.0,
                "output_rms_nm": 0.8}

    monkeypatch.setattr(br, "process_one", fake_process)
    report = br.run_copilot(root)

    assert report["cases"] == 1
    assert report["copilot_outputs"] == 1
    assert report["states"] == {"generated_for_review": 1}
    assert Path(seen[0][0]) == raw.resolve()
    assert Path(seen[0][1]) == manual.resolve()
    saved = json.loads(br.RUN_MANIFEST.read_text(encoding="utf-8"))
    assert saved["pairs"][0]["case"] == "case-001"
