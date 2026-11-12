"""Run AFM Copilot on the neutral benchmark copies and prepare blind sanitized export.

The benchmark is intentionally two-stage:
1) AFM Copilot processes only benchmark/originals and writes benchmark/copilot.
2) External review receives ONLY sanitized blind_inputs first. Manual and Copilot
   references remain in a separate reference folder until the planner commits.

No raw instrument metadata or original filenames are written to blind_inputs.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from afm_copilot.auto_compare import process_one
from afm_copilot.benchmark_corpus import DESTINATION
from afm_copilot.gwy_io import load_height, save_height
from afm_copilot.labeler import _load

ROOT = DESTINATION
RUN_MANIFEST = ROOT / "benchmark_auto_manifest.json"
BLIND = ROOT / "share" / "blind_inputs"
REFERENCE = ROOT / "share" / "reference"


def _read_cases(root: Path) -> list[dict]:
    manifest = root / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark manifest has no cases")
    return cases


def _load_neutral(path: Path, scratch: Path):
    if path.suffix.lower() == ".gwy":
        return load_height(path)
    channel, _ = _load(path, scratch)
    return channel


def run_copilot(root: Path = ROOT) -> dict:
    root = root.expanduser().resolve()
    cases = _read_cases(root)
    rows = []
    states = {}
    scratch = root / "_copilot_scratch"
    output = root / "copilot"
    output.mkdir(parents=True, exist_ok=True)

    for case in cases:
        original = (root / case["original"]).resolve()
        manual = (root / case["manual"]).resolve()
        row = {"original": str(original), "manual": str(manual), "automated": None}
        result = process_one(row, output=output, scratch=scratch)
        state = result["state"]
        states[state] = states.get(state, 0) + 1
        rows.append({
            "case": case["case"],
            "original": str(original),
            "manual": str(manual),
            "automated": row.get("automated"),
            "state": state,
            "recipe": result.get("recipe"),
            "steps_applied": result.get("steps_applied", []),
            "steps_held": result.get("steps_held", []),
            "source_rms_nm": result.get("source_rms_nm"),
            "output_rms_nm": result.get("output_rms_nm"),
        })

    run_manifest = root / "benchmark_auto_manifest.json"
    run_manifest.write_text(json.dumps(
        {"schema_version": 1, "pairs": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    return {
        "cases": len(cases),
        "states": dict(sorted(states.items())),
        "copilot_outputs": sum(bool(r["automated"]) for r in rows),
        "source_files_modified": False,
    }


def prepare_share(root: Path = ROOT) -> dict:
    root = root.expanduser().resolve()
    cases = _read_cases(root)
    run_manifest = root / "benchmark_auto_manifest.json"
    blind = root / "share" / "blind_inputs"
    reference = root / "share" / "reference"
    run_data = {}
    if run_manifest.is_file():
        run_payload = json.loads(run_manifest.read_text(encoding="utf-8"))
        run_data = {r["case"]: r for r in run_payload.get("pairs", [])}

    if blind.exists():
        shutil.rmtree(blind)
    if reference.exists():
        shutil.rmtree(reference)
    blind.mkdir(parents=True)
    reference.mkdir(parents=True)
    scratch = root / "_share_scratch"

    blind_manifest = {"schema_version": 1, "cases": []}
    reference_manifest = {"schema_version": 1, "cases": []}
    blind_ok = 0
    manual_ok = 0
    copilot_ok = 0

    for case in cases:
        case_id = case["case"]
        original = (root / case["original"]).resolve()
        manual = (root / case["manual"]).resolve()

        try:
            raw_channel = _load_neutral(original, scratch / case_id / "raw")
            raw_channel.name = "Height"
            raw_channel.meta = {}
            raw_channel.source = None
            raw_out = blind / f"{case_id}.gwy"
            save_height(raw_channel, raw_out)
            blind_manifest["cases"].append({
                "case": case_id,
                "file": raw_out.name,
                "xres": raw_channel.xres,
                "yres": raw_channel.yres,
                "xreal_um": round(raw_channel.xreal * 1e6, 6),
                "yreal_um": round(raw_channel.yreal * 1e6, 6),
                "rms_nm": round(raw_channel.rms * 1e9, 6),
                "z_range_nm": round(raw_channel.z_range * 1e9, 6),
            })
            blind_ok += 1
        except Exception as error:
            blind_manifest["cases"].append({
                "case": case_id, "error": type(error).__name__})

        ref = {"case": case_id}
        try:
            manual_channel = _load_neutral(manual, scratch / case_id / "manual")
            manual_channel.name = "Height"
            manual_channel.meta = {}
            manual_channel.source = None
            manual_out = reference / f"{case_id}-manual.gwy"
            save_height(manual_channel, manual_out)
            ref["manual"] = manual_out.name
            manual_ok += 1
        except Exception as error:
            ref["manual_error"] = type(error).__name__

        run = run_data.get(case_id, {})
        auto = run.get("automated")
        if auto and Path(auto).is_file():
            try:
                auto_channel = load_height(auto)
                auto_channel.name = "Height"
                auto_channel.meta = {}
                auto_channel.source = None
                auto_out = reference / f"{case_id}-copilot.gwy"
                save_height(auto_channel, auto_out)
                ref["copilot"] = auto_out.name
                copilot_ok += 1
            except Exception as error:
                ref["copilot_error"] = type(error).__name__
        else:
            ref["copilot_state"] = run.get("state", "not_run")

        reference_manifest["cases"].append(ref)

    (blind / "manifest.json").write_text(
        json.dumps(blind_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (reference / "manifest.json").write_text(
        json.dumps(reference_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "cases": len(cases),
        "blind_inputs_sanitized": blind_ok,
        "manual_references_sanitized": manual_ok,
        "copilot_references_sanitized": copilot_ok,
        "blind_folder": str(blind),
        "reference_folder": str(reference),
        "raw_metadata_in_blind_inputs": False,
        "original_filenames_in_blind_inputs": False,
        "upload_blind_first": True,
        "source_files_modified": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--run-copilot", action="store_true")
    parser.add_argument("--prepare-share", action="store_true")
    parser.add_argument(
        "--confirm", choices=("RUN_BLIND_BENCHMARK",), required=True)
    args = parser.parse_args(argv)
    if not args.run_copilot and not args.prepare_share:
        parser.error("choose --run-copilot and/or --prepare-share")
    result = {}
    if args.run_copilot:
        result["copilot"] = run_copilot(args.root)
    if args.prepare_share:
        result["share"] = prepare_share(args.root)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
