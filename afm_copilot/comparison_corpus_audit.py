"""Private audit of the curated manual-vs-automatic AFM comparison corpus.

Reads the 17-pair private manifest and any generated derivatives. It does not
run Gwyddion, alter associations, approve corrections, or scan the large AFM
archive. Exact paths stay in the private JSON; stdout contains aggregates only.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from afm_copilot.auto_compare import MANIFEST, OUTPUT, _id
from afm_copilot.comparison_metrics import shape_comparison
from afm_copilot.gwy_io import load_height
from afm_copilot.labeler import _load
from afm_copilot.manual_pairs import PRIVATE_ROOT

PRIVATE_REPORT = PRIVATE_ROOT / "PRIVATE_comparison_corpus_audit.json"


def _candidate_for(raw: Path, output: Path) -> Path:
    return output / _id(raw) / "corrected" / "height.gwy"


def _load_any(path: Path, scratch: Path):
    if path.suffix.lower() == ".gwy":
        return load_height(path)
    channel, _ = _load(path, scratch)
    return channel


def audit(manifest: Path = MANIFEST, output: Path = OUTPUT) -> dict:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    rows = data.get("pairs", [])
    if not isinstance(rows, list):
        raise ValueError("Comparison manifest has no pairs list")

    details = []
    states = Counter()
    comparable = 0
    manual_auto_rmse = []
    held_candidates = 0
    scratch = PRIVATE_ROOT / "audit_scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    for index, row in enumerate(rows):
        raw = Path(row["original"]).resolve()
        manual = Path(row["manual"]).resolve()
        associated = Path(row["automated"]).resolve() if row.get("automated") else None
        generated = _candidate_for(raw, output) if raw.is_file() else None

        if associated and associated.is_file():
            auto = associated
            state = "associated_automatic"
        elif generated and generated.is_file():
            auto = generated
            state = "held_generated_candidate"
            held_candidates += 1
        else:
            auto = None
            state = "no_automatic_candidate"
        states[state] += 1

        entry = {
            "index": index,
            "state": state,
            "original": str(raw),
            "manual": str(manual),
            "automatic": str(auto) if auto else None,
            "associated": bool(associated and associated.is_file()),
        }

        try:
            if raw.is_file():
                raw_channel = _load_any(raw, scratch / f"raw-{index}")
                entry["raw_rms_nm"] = round(raw_channel.rms * 1e9, 4)
            else:
                raw_channel = None
        except Exception as error:
            raw_channel = None
            entry["raw_error"] = type(error).__name__

        try:
            manual_channel = _load_any(manual, scratch / f"manual-{index}")
            entry["manual_rms_nm"] = round(manual_channel.rms * 1e9, 4)
        except Exception as error:
            manual_channel = None
            entry["manual_error"] = type(error).__name__

        try:
            auto_channel = _load_any(auto, scratch / f"auto-{index}") if auto else None
            if auto_channel is not None:
                entry["automatic_rms_nm"] = round(auto_channel.rms * 1e9, 4)
        except Exception as error:
            auto_channel = None
            entry["automatic_error"] = type(error).__name__

        if raw_channel is not None and auto_channel is not None and raw_channel.rms > 0:
            entry["automatic_rms_change_fraction"] = round(
                (auto_channel.rms - raw_channel.rms) / raw_channel.rms, 4)

        if manual_channel is not None and auto_channel is not None:
            comparison = shape_comparison(manual_channel, auto_channel)
            entry["manual_vs_automatic"] = comparison
            if comparison.get("comparable"):
                comparable += 1
                manual_auto_rmse.append(float(comparison["shape_rmse_nm"]))

        details.append(entry)

    return {
        "schema_version": 1,
        "summary": {
            "pairs": len(rows),
            "states": dict(sorted(states.items())),
            "held_generated_candidates": held_candidates,
            "manual_auto_comparable": comparable,
            "manual_auto_rmse_nm_median": (
                round(sorted(manual_auto_rmse)[len(manual_auto_rmse)//2], 4)
                if manual_auto_rmse else None
            ),
            "source_files_modified": False,
            "associations_modified": False,
            "gwyddion_executed": False,
        },
        "pairs": details,
    }


def save_private(report: dict, path: Path = PRIVATE_REPORT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if not args.manifest.is_file():
        print(json.dumps({"error": "comparison_manifest_missing"}))
        return 2
    report = audit(args.manifest, args.output)
    save_private(report)
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
