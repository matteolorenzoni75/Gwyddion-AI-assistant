"""Find operator-corrected AFM files and matching original/automated versions.

Read-only, local-only. Never copies or exports image data.
Original filename/path mapping is private; stdout emits only counts.
Default search deliberately excludes the huge All AFM Data archive so the
organizer may continue hashing it independently.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

from afm_copilot.labeling import FORMATS

DEFAULT_SEARCH = (
    Path(r"C:\AFM_Automation\OLD input IMAGES"),
    Path(r"C:\AFM_Automation\corrected"),
    Path(r"C:\AFM_Automation\processed"),
    Path(r"C:\AFM_image_wizard\out"),
)
PRIVATE_ROOT = Path.home() / "AFM_Copilot_Private_Audits" / "manual_comparisons"
TAG = re.compile(r"(?i)(?:[\s_.-]+(?:corrected|manual|hand[-_ ]?fixed|flattened|levelled|leveled|processed|cleaned|afm[-_ ]?copilot))")
MANUAL = re.compile(r"(?i)(corrected|manual|hand[-_ ]?fixed|flattened|levelled|leveled)")
AUTO = re.compile(r"(?i)(processed|cleaned|afm[-_ ]?copilot|automatic|auto[-_ ]?corrected)")
SKIP = {".git", ".venv", "__pycache__", "node_modules", "All AFM Data"}
# Operator may have saved a Gwyddion document with a nonstandard extension
# after "corrected"; it is considered a candidate for review, NOT loaded by
# automatically guessing the format.
SUPPORTED = set(FORMATS) | {".gwy"}


def _key(path: Path) -> str:
    text = path.name
    # Corrected exports may have arbitrary trailing process notes.
    text = TAG.split(text, maxsplit=1)[0]
    if Path(text).suffix.lower() in SUPPORTED:
        text = Path(text).stem
    return re.sub(r"[\W_]+", "", text.casefold())


def scan_folder(root: Path, *, max_files=100000) -> dict:
    root = root.expanduser().resolve()
    if not root.is_dir():
        return {"root": str(root), "pairs": [], "candidates": 0, "scanned": 0}
    by_key = {}
    candidates = []
    scanned = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        here = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in SKIP
                         and not (here / d).is_symlink())
        for filename in sorted(files):
            p = here / filename
            if not p.is_file() or p.is_symlink():
                continue
            scanned += 1
            if scanned > max_files:
                break
            # Name may have a suffix-less instrument export with 'corrected'.
            if p.suffix.lower() not in SUPPORTED and not MANUAL.search(p.name):
                continue
            key = _key(p)
            if not key:
                continue
            kind = ("manual" if MANUAL.search(p.name) and not AUTO.search(p.name)
                    else "auto" if AUTO.search(p.name) else "original")
            by_key.setdefault((str(p.parent).casefold(), key), {}).setdefault(kind, []).append(p)
            if kind == "manual":
                candidates.append(p)
        if scanned > max_files:
            break
    pairs = []
    # Conservative: sibling group only; do not join samples with matching
    # basenames in different folders, instruments or sessions.
    for group in by_key.values():
        if not group.get("manual"):
            continue
        raw, manual, automated = (group.get(k, []) for k in ("original", "manual", "auto"))
        if len(raw) == 1 and len(manual) == 1:
            pairs.append({
                "original": str(raw[0]), "manual": str(manual[0]),
                "automated": str(automated[0]) if len(automated) == 1 else None,
                "status": "candidate_needs_image_verification",
            })
    return {"root": str(root), "pairs": pairs, "candidates": len(candidates),
            "scanned": scanned, "truncated": scanned > max_files}


def inventory(roots=DEFAULT_SEARCH) -> dict:
    data = [scan_folder(Path(root)) for root in roots]
    pairs = [p for item in data for p in item["pairs"]]
    return {"schema_version": 1, "pairs": pairs,
            "summary": {
                "directories_searched": sum(Path(r).is_dir() for r in roots),
                "files_inspected": sum(item["scanned"] for item in data),
                "manual_named_candidates": sum(item["candidates"] for item in data),
                "unambiguous_original_manual_candidates": len(pairs),
                "triplets_with_auto_candidate": sum(p["automated"] is not None for p in pairs),
                "incomplete_or_ambiguous": sum(item["candidates"] for item in data) - len(pairs),
                "search_truncated": any(item["truncated"] for item in data),
                "verified_by_pixels": False,
                "private_only": True,
            }}


def save_private(results: dict, path: Path | None = None) -> Path:
    from afm_copilot.feedback import PROJECT_ROOT
    path = path or PRIVATE_ROOT / "PRIVATE_manual_pair_candidates.json"
    out = path.expanduser().resolve()
    repo = PROJECT_ROOT.resolve()
    if repo == out or repo in out.parents:
        raise ValueError("Private paths cannot be written inside the Git checkout")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, action="append",
                        help="Search this local folder (repeat to include several)")
    parser.add_argument("--max-files", type=int, default=100000)
    args = parser.parse_args(argv)
    if args.max_files < 1:
        parser.error("--max-files must be positive")
    roots = args.root or DEFAULT_SEARCH
    results = {"schema_version": 1, "roots": [str(x) for x in roots],
               "pairs": [], "summary": {}}
    chunks = [scan_folder(Path(root), max_files=args.max_files) for root in roots]
    results["pairs"] = [p for part in chunks for p in part["pairs"]]
    results["summary"] = {
        "directories_searched": sum(Path(x).is_dir() for x in roots),
        "files_inspected": sum(c["scanned"] for c in chunks),
        "manual_named_candidates": sum(c["candidates"] for c in chunks),
        "candidate_pairs": len(results["pairs"]),
        "with_automatic_candidate": sum(p["automated"] is not None for p in results["pairs"]),
        "unresolved": sum(c["candidates"] for c in chunks) - len(results["pairs"]),
        "scan_truncated": any(c["truncated"] for c in chunks),
        "pixel_verified": False,
        "no_source_modified": True,
    }
    save_private(results)
    print(json.dumps(results["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
