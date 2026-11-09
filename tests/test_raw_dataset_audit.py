"""No real AFM files needed: test privacy and inventory accounting."""
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "tools" / "audit_raw_dataset.py"
spec = importlib.util.spec_from_file_location("afm_raw_audit", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_recursive_discovery_casefolded_extensions_and_no_symlink(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.IBW").write_bytes(b"ibw")
    (tmp_path / "sub" / "b.TIFF").write_bytes(b"tiff")
    (tmp_path / "sub" / "ignore.jpg").write_bytes(b"jpg")
    assert len(audit.discover(tmp_path)) == 2


def test_collisions_are_flagged_even_with_different_extensions(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "same.ibw").write_bytes(b"a")
    (tmp_path / "sub" / "SAME.TIFF").write_bytes(b"b")
    private, shared = audit.make_entries(audit.discover(tmp_path), tmp_path)
    assert len(private) == 2
    assert all(row["basename_collision"] for row in shared)
    assert all("relative_path" not in row for row in shared)


def test_shareable_archive_does_not_contain_names_paths_or_notes(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    secret = "confidential_Perovskite_Collaborator_101.ibw"
    (source / secret).write_bytes(b"raw")
    private, shared = audit.make_entries(audit.discover(source), source)
    out = tmp_path / "reports"
    summary = audit.build_summary(shared, source, False)
    archive = audit.write_reports(out, private, shared, summary)
    assert secret in (out / "PRIVATE_manifest.csv").read_text(encoding="utf-8-sig")
    with zipfile.ZipFile(archive) as z:
        assert sorted(z.namelist()) == ["CHATGPT_results.json", "CHATGPT_summary.json", "CHATGPT_summary.md"]
        content = "\n".join(z.read(name).decode("utf-8") for name in z.namelist())
        assert secret not in content
        assert str(source) not in content
        assert "PRIVATE" not in " ".join(z.namelist())
        assert json.loads(z.read("CHATGPT_summary.json"))["n_files"] == 1


def test_output_must_be_outside_source_and_repo(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    with pytest.raises(ValueError):
        audit.validate_output(source, source / "report")
    with pytest.raises(ValueError):
        audit.validate_output(source, audit.REPO / "reports")


def test_inventory_only_without_instrument(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    (source / "a.ibw").write_bytes(b"nonsense")
    out = tmp_path / "private"
    assert audit.main(["--root", str(source), "--out", str(out), "--inventory-only"]) == 0
    with zipfile.ZipFile(out / "CHATGPT_REVIEW.zip") as z:
        summary = json.loads(z.read("CHATGPT_summary.json"))
        assert summary["calibration_probed"] is False
        assert summary["formats"] == {".ibw": 1}


def test_probe_whitelists_sensitive_importer_fields(tmp_path, monkeypatch):
    import afm_copilot.bridge as bridge

    source = tmp_path / "raw"
    source.mkdir()
    filename = "private_collaborator_42.tiff"
    (source / filename).write_bytes(b"sample")
    private, shared = audit.make_entries(audit.discover(source), source)

    class FakeGwyBridge:
        def run_script(self, script, args, timeout):
            assert script == "audit_raw_channels.py"
            return {"results": [{
                "id": private[0]["id"], "status": "ok",
                "n_height": 1, "trace_retrace_height": False,
                "source": filename, "private_notes": "secret sample name",
                "channels": [{
                    "title": filename, "kind": "height", "direction": "retrace",
                    "xres": 256, "yres": 256, "xreal_m": 5e-6, "yreal_m": 5e-6,
                    "xy_unit": "m", "z_unit": "m", "z_range_si": 1e-8,
                    "calibration_ok": True, "metadata": {"secret": filename},
                }],
            }]}

    monkeypatch.setattr(bridge, "GwyBridge", FakeGwyBridge)
    audit._run_probes(private, shared, tmp_path / "report", 2)
    report = json.dumps(shared)
    assert "private" not in report
    assert "secret" not in report
    assert shared[0]["status"] == "ok"
    assert shared[0]["channels"][0]["calibration_ok"] is True


def test_unrealistic_metric_extent_is_flagged_not_corrected(tmp_path):
    rows = [{
        "id": "AFM-99999", "format": ".ibw", "status": "ok",
        "basename_collision": False, "n_height": 1,
        "trace_retrace_height": False, "igor_note_present": False,
        "channels": [{
            "kind": "height", "calibration_ok": True,
            "xreal_m": 13.46, "yreal_m": 12.46,
        }],
    }]
    summary = audit.build_summary(rows, tmp_path, True)
    assert summary["calibration_flags"]["height_xy_extent_gt_1mm_review"] == 1
    assert summary["extent_outlier_anonymous_ids"] == ["AFM-99999"]
    assert rows[0]["channels"][0]["xreal_m"] == 13.46
