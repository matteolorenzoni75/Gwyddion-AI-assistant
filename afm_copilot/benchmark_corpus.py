"""Build a blind local benchmark corpus from operator-corrected AFM pairs.

Copies, never moves, the known original/manual pairs into a neutral workspace:
    benchmark/
        originals/case-001.<ext>
        manual/case-001.<ext>
        copilot/
        manifest.json

The local copies are byte-identical to the sources. Therefore this module is
NOT an upload/anonymisation tool: raw instrument metadata may still contain
private names. A separate sanitized export must be made before sharing cases
with any external model or service.

Exact source paths are stored only in the private audit mapping outside Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from afm_copilot.directory_map import WORKSPACE
from afm_copilot.manual_pairs import (
    DEFAULT_SEARCH, PRIVATE_ROOT, SKIP, SUPPORTED, _key,
)

PAIR_MANIFEST = PRIVATE_ROOT / "PRIVATE_manual_pair_candidates.json"
DESTINATION = WORKSPACE / "benchmark"
PRIVATE_MAPPING = PRIVATE_ROOT / "PRIVATE_benchmark_mapping.json"
DISCOVERY = PRIVATE_ROOT / "PRIVATE_corrected_discovery.json"


def _sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _copy_exact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or _sha256(destination) != _sha256(source):
            raise FileExistsError(
                f"Benchmark destination already exists with different content: {destination}")
        return
    shutil.copy2(source, destination)
    if _sha256(source) != _sha256(destination):
        destination.unlink(missing_ok=True)
        raise IOError("Copied benchmark file failed SHA-256 verification")



def discover_corrected_pairs(roots=DEFAULT_SEARCH) -> dict:
    """Find every sibling file explicitly tagged 'corrected' and its twin.

    This is broader than the historical pair manifest. Pairing is conservative:
    the original must be in the same directory and reduce to the same neutral
    key. Missing or ambiguous twins are reported and never guessed.
    """
    pairs = []
    unresolved = []
    corrected_seen = 0
    inspected = 0

    for root in roots:
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            continue
        for current, dirs, files in os.walk(root, followlinks=False):
            here = Path(current)
            dirs[:] = sorted(
                d for d in dirs
                if d not in SKIP and not (here / d).is_symlink()
            )
            siblings = [here / name for name in sorted(files)]
            for path in siblings:
                if not path.is_file() or path.is_symlink():
                    continue
                inspected += 1
                if "corrected" not in path.name.casefold():
                    continue
                corrected_seen += 1
                key = _key(path)
                candidates = []
                for other in siblings:
                    if other == path or not other.is_file() or other.is_symlink():
                        continue
                    if "corrected" in other.name.casefold():
                        continue
                    if other.suffix.lower() not in SUPPORTED:
                        continue
                    if _key(other) == key:
                        candidates.append(other.resolve())
                unique = sorted(set(candidates))
                if len(unique) == 1:
                    pairs.append({
                        "original": str(unique[0]),
                        "manual": str(path.resolve()),
                        "automated": None,
                        "status": "discovered_from_corrected_tag",
                    })
                else:
                    unresolved.append({
                        "corrected": str(path.resolve()),
                        "candidate_originals": [str(x) for x in unique],
                        "reason": "missing_twin" if not unique else "ambiguous_twin",
                    })

    # Exact path-pair deduplication only; never deduplicate by specimen name.
    dedup = {}
    for row in pairs:
        dedup[(row["original"], row["manual"])] = row
    pairs = list(dedup.values())
    return {
        "pairs": pairs,
        "summary": {
            "files_inspected": inspected,
            "corrected_tagged": corrected_seen,
            "paired": len(pairs),
            "unresolved": len(unresolved),
            "source_files_modified": False,
        },
        "unresolved": unresolved,
    }


def _write_private_discovery(report: dict, path: Path = DISCOVERY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def build(
    manifest: Path = PAIR_MANIFEST,
    destination: Path = DESTINATION,
    private_mapping: Path = PRIVATE_MAPPING,
    *,
    discover_all_corrected: bool = False,
) -> dict:
    manifest = manifest.expanduser().resolve()
    destination = destination.expanduser().resolve()
    private_mapping = private_mapping.expanduser().resolve()

    if discover_all_corrected:
        discovered = discover_corrected_pairs()
        _write_private_discovery(discovered)
        rows = discovered["pairs"]
        if not rows:
            raise ValueError("No unambiguous corrected/original pairs discovered")
    else:
        if not manifest.is_file():
            raise FileNotFoundError("Private original/manual pair manifest not found")
        if destination == manifest.parent or destination in manifest.parent.parents:
            raise ValueError("Benchmark destination overlaps private manifest folder")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        rows = payload.get("pairs")
        if not isinstance(rows, list) or not rows:
            raise ValueError("Private pair manifest contains no comparison pairs")

    originals_dir = destination / "originals"
    manual_dir = destination / "manual"
    copilot_dir = destination / "copilot"
    for folder in (originals_dir, manual_dir, copilot_dir):
        folder.mkdir(parents=True, exist_ok=True)

    public_cases = []
    private_cases = []
    copied = 0
    reused = 0

    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not row.get("original") or not row.get("manual"):
            raise ValueError(f"Malformed pair at index {index - 1}")
        original = Path(row["original"]).expanduser().resolve()
        manual = Path(row["manual"]).expanduser().resolve()
        if not original.is_file() or not manual.is_file() or original == manual:
            raise ValueError(f"Missing/invalid source pair at index {index - 1}")

        case_id = f"case-{index:03d}"
        original_copy = originals_dir / f"{case_id}{original.suffix.lower()}"
        manual_copy = manual_dir / f"{case_id}{manual.suffix.lower()}"

        before = int(original_copy.exists()) + int(manual_copy.exists())
        _copy_exact(original, original_copy)
        _copy_exact(manual, manual_copy)
        after = int(original_copy.exists()) + int(manual_copy.exists())
        reused += before
        copied += max(0, after - before)

        original_hash = _sha256(original)
        manual_hash = _sha256(manual)
        public_cases.append({
            "case": case_id,
            "original": str(Path("originals") / original_copy.name),
            "manual": str(Path("manual") / manual_copy.name),
            "copilot_expected_prefix": str(Path("copilot") / case_id),
            "source_bytes_preserved": True,
        })
        private_cases.append({
            "case": case_id,
            "original_source": str(original),
            "manual_source": str(manual),
            "original_copy": str(original_copy),
            "manual_copy": str(manual_copy),
            "original_sha256": original_hash,
            "manual_sha256": manual_hash,
            "prior_automatic": row.get("automated"),
        })

    public_manifest = {
        "schema_version": 1,
        "purpose": "blind_manual_vs_afm_copilot_vs_external_planner_benchmark",
        "cases": public_cases,
        "notes": [
            "Files are local byte-identical copies; source files were not modified.",
            "Neutral filenames do not remove metadata embedded inside raw files.",
            "Do not upload this raw corpus externally; create a sanitized export first.",
            "Manual corrections are candidate expert references until explicitly approved.",
        ],
    }
    manifest_out = destination / "manifest.json"
    tmp = manifest_out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(public_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(manifest_out)

    private_mapping.parent.mkdir(parents=True, exist_ok=True)
    private_payload = {
        "schema_version": 1,
        "benchmark_root": str(destination),
        "cases": private_cases,
    }
    tmp_private = private_mapping.with_suffix(".json.tmp")
    tmp_private.write_text(
        json.dumps(private_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_private.replace(private_mapping)

    return {
        "pairs": len(rows),
        "files_expected": len(rows) * 2,
        "files_copied_now": copied,
        "files_reused_identical": reused,
        "benchmark_root": str(destination),
        "source_files_modified": False,
        "source_files_moved": False,
        "sha256_verified": True,
        "safe_for_external_upload": False,
        "discovery_mode": "all_corrected" if discover_all_corrected else "manifest",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PAIR_MANIFEST)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument(
        "--all-corrected", action="store_true",
        help="discover every sibling '*corrected*' file in known AFM folders")
    parser.add_argument(
        "--confirm", choices=("BUILD_BLIND_BENCHMARK",), required=True,
        help="Explicitly confirm copying curated pairs into the benchmark workspace.")
    args = parser.parse_args(argv)
    try:
        report = build(
            args.manifest, args.destination,
            discover_all_corrected=args.all_corrected)
    except Exception as error:
        print(json.dumps({
            "error": type(error).__name__,
            "message": str(error),
            "source_files_modified": False,
        }, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
