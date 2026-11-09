"""Read-only inventory and calibration audit of private AFM instrument files.

Run from the repository root:
    .venv\Scripts\python.exe tools\audit_raw_dataset.py

Original filenames and paths stay in PRIVATE_manifest.csv, outside Git.
The CHATGPT_REVIEW.zip contains only anonymous IDs, diagnostic numbers and
aggregate results. It never includes images, original filenames or scan notes.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_INPUT = Path(r"C:\AFM_Automation\OLD input IMAGES")
EXTENSIONS = {".ibw", ".tif", ".tiff"}
REPO = Path(__file__).resolve().parent.parent


def discover(root: Path) -> list[Path]:
    """Do not traverse symlinked directories; return only raw instrument files."""
    found = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            candidate = Path(directory) / name
            if candidate.is_file() and not candidate.is_symlink() and candidate.suffix.lower() in EXTENSIONS:
                found.append(candidate)
    return sorted(found, key=lambda p: str(p.relative_to(root)).casefold())


def make_entries(paths: list[Path], root: Path) -> tuple[list[dict], list[dict]]:
    """Produce a private reversible map and anonymous shareable rows."""
    by_stem = defaultdict(list)
    for p in paths:
        by_stem[p.stem.casefold()].append(p)
    private, public = [], []
    for idx, path in enumerate(paths, 1):
        scan_id = f"AFM-{idx:05d}"
        stat = path.stat()
        private.append({
            "id": scan_id, "relative_path": str(path.relative_to(root)),
            "absolute_path": str(path), "bytes": stat.st_size,
            "extension": path.suffix.lower(),
        })
        public.append({
            "id": scan_id, "format": path.suffix.lower(),
            "bytes": stat.st_size,
            "basename_collision": len(by_stem[path.stem.casefold()]) > 1,
            "status": "not_probed", "channels": [], "n_height": None,
            "trace_retrace_height": None, "igor_note_present": None,
        })
    return private, public


def validate_output(root: Path, out: Path) -> None:
    """Never write the audit into source data or a public Git checkout."""
    rp, op = root.resolve(), out.resolve()
    repo = REPO.resolve()
    if op == rp or rp in op.parents:
        raise ValueError("The output must be outside the private raw-data folder")
    if op == repo or repo in op.parents:
        raise ValueError("The output must be outside the Git repository")


def _run_probes(private: list[dict], public: list[dict], out: Path, chunk_size: int) -> dict:
    """Call the Gwyddion importer without converting or writing any scan."""
    from afm_copilot.bridge import BridgeError, GwyBridge

    bridge = GwyBridge()
    by_id = {r["id"]: r for r in public}
    job = out / "PRIVATE_probe_job.json"
    total_errors = 0

    def probe(group: list[dict]) -> None:
        nonlocal total_errors
        job.write_text(json.dumps({"files": [
            {"id": r["id"], "path": r["absolute_path"]} for r in group
        ]}, ensure_ascii=False), encoding="utf-8")
        try:
            answer = bridge.run_script("audit_raw_channels.py", ["--job", str(job)], timeout=600)
        except (BridgeError, OSError):
            if len(group) > 1:
                middle = len(group) // 2
                probe(group[:middle])
                probe(group[middle:])
            else:
                by_id[group[0]["id"]]["status"] = "probe_crashed"
                total_errors += 1
            return
        seen = set()
        group_ids = {r["id"] for r in group}
        for record in answer.get("results", []):
            rid = record.get("id")
            if rid not in by_id or rid not in group_ids:
                continue
            seen.add(rid)
            target = by_id[rid]
            # Deliberately whitelist fields: no raw paths, names, metadata
            # values, Gwyddion stderr or vendor-provided channel titles.
            for key in ("status", "n_height", "trace_retrace_height"):
                if key in record:
                    target[key] = record[key]
            target["channels"] = [
                {k: c.get(k) for k in (
                    "kind", "direction", "xres", "yres", "xreal_m", "yreal_m",
                    "xy_unit", "z_unit", "z_range_si", "calibration_ok")}
                for c in record.get("channels", [])
            ]
            if target["status"] != "ok":
                total_errors += 1
        for item in group:
            if item["id"] not in seen:
                by_id[item["id"]]["status"] = "missing_probe_result"
                total_errors += 1

    for start in range(0, len(private), chunk_size):
        probe(private[start:start + chunk_size])
        print(f"Calibration audit: {min(start + chunk_size, len(private))}/{len(private)} files", flush=True)
    return {"read_errors": total_errors}


def _inspect_igor(private: list[dict], public: list[dict]) -> None:
    """Read the Igor note independently; never export its actual contents."""
    try:
        from afm_copilot.instrument import read
    except ImportError:
        return
    for local, row in zip(private, public):
        if row["format"] != ".ibw":
            continue
        try:
            record = read(local["absolute_path"])
            row["igor_note_present"] = bool(record.known)
        except Exception:
            row["igor_note_present"] = False


def build_summary(rows: list[dict], root: Path, probed: bool) -> dict:
    statuses = Counter(r["status"] for r in rows)
    formats = Counter(r["format"] for r in rows)
    calibration = Counter()
    for row in rows:
        if row["status"] == "ok":
            if not row["channels"]:
                calibration["no_2d_channel"] += 1
            if row["n_height"] == 0:
                calibration["no_height_channel"] += 1
            if any(c.get("calibration_ok") is False for c in row["channels"] if c.get("kind") == "height"):
                calibration["unverified_height_calibration"] += 1
    return {
        "schema_version": 1, "generated": datetime.now().astimezone().isoformat(),
        "source": "local_private_folder", "recursive": True,
        "source_root_exists": root.is_dir(), "n_files": len(rows),
        "formats": dict(sorted(formats.items())), "statuses": dict(sorted(statuses.items())),
        "basename_collisions": sum(r["basename_collision"] for r in rows),
        "calibration_flags": dict(sorted(calibration.items())),
        "with_trace_retrace_height_pair": sum(r["trace_retrace_height"] is True for r in rows),
        "calibration_probed": probed,
        "igor_notes_present": sum(r["igor_note_present"] is True for r in rows),
        "igor_notes_missing_or_unreadable": sum(r["igor_note_present"] is False for r in rows),
        "warning": "No numerical or morphological correction performed. Channel data not exported. Filenames only in private manifest.",
    }


def write_reports(out: Path, private: list[dict], public: list[dict], summary: dict) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    if private:
        with (out / "PRIVATE_manifest.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(private[0]))
            writer.writeheader()
            writer.writerows(private)
    else:
        (out / "PRIVATE_manifest.csv").write_text("id,relative_path,absolute_path,bytes,extension\n", encoding="utf-8")
    (out / "CHATGPT_results.json").write_text(json.dumps(public, indent=2, allow_nan=False), encoding="utf-8")
    (out / "CHATGPT_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    lines = [
        "# AFM raw data audit (shareable)", "",
        f"- Files found: **{summary['n_files']}**",
        f"- Formats: **{summary['formats']}**",
        f"- Import statuses: **{summary['statuses']}**",
        f"- Files with basename collisions: **{summary['basename_collisions']}**",
        f"- Height trace+retrace pairs: **{summary['with_trace_retrace_height_pair']}**",
        f"- Calibration probed with Gwyddion: **{summary['calibration_probed']}**",
        f"- Calibration flags: **{summary['calibration_flags']}**", "",
        "The private filename/ID map is NOT in the shareable ZIP.",
        "No raw images, note values, or sample names are included.",
    ]
    (out / "CHATGPT_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    archive = out / "CHATGPT_REVIEW.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for filename in ("CHATGPT_results.json", "CHATGPT_summary.json", "CHATGPT_summary.md"):
            zipped.write(out / filename, arcname=filename)
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("AFM_RAW_ROOT", str(DEFAULT_INPUT))))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--inventory-only", action="store_true", help="do not open Gwyddion or inspect instrument channels")
    parser.add_argument("--max-files", type=int, default=0, help="limit for a smoke test; 0 checks everything")
    parser.add_argument("--chunk", type=int, default=12, help="files per PyGwy probe subprocess")
    args = parser.parse_args(argv)
    if args.chunk < 1 or args.max_files < 0:
        parser.error("--chunk must be positive and --max-files cannot be negative")
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print("Raw dataset folder not found: " + str(root), file=sys.stderr)
        return 2
    out = args.out or (Path.home() / "AFM_Copilot_Private_Audits" / datetime.now().strftime("%Y%m%d_%H%M%S"))
    out = out.expanduser().resolve()
    try:
        validate_output(root, out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    files = discover(root)
    if args.max_files:
        files = files[:args.max_files]
    private, public = make_entries(files, root)
    print(f"Found {len(public)} TIFF/IBW files under private root (recursive).")
    _inspect_igor(private, public)
    probed = False
    if not args.inventory_only and files:
        try:
            from afm_copilot.bridge import BridgeError
            _run_probes(private, public, out, args.chunk)
            probed = True
        except (ImportError, BridgeError, OSError):
            print("Gwyddion unavailable: channel/calibration checks not performed.", file=sys.stderr)
    summary = build_summary(public, root, probed)
    archive = write_reports(out, private, public, summary)
    print("\nFINISHED. Private manifest (DO NOT UPLOAD): " + str(out / "PRIVATE_manifest.csv"))
    print("Upload ONLY: " + str(archive))
    return 0 if files else 3


if __name__ == "__main__":
    raise SystemExit(main())
