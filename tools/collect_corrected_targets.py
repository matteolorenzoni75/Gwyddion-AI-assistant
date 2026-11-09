"""Collect operator-corrected AFM targets without exposing source filenames.

An operator can save a corrected copy as either ``name corrected.tiff`` or
``name.ibw corrected with ...``.  The latter is a perfectly readable Gwyddion
file, but no longer has a suffix that the batch collector accepts.  This tool
copies both sides of each pair under blind ordinal names, restoring the
original suffix for the corrected side.  It never renames, edits or deletes a
source file.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


CORRECTED = re.compile(r"\s+corrected\b", re.IGNORECASE)


def _operator_hint(name: str) -> str:
    """A review label only; no processing decision is made from a filename."""
    lower = name.lower()
    if any(token in lower for token in ("facet", "terrace", "level data")):
        return "facet-level review"
    if any(token in lower for token in ("mask", "polynom", "median")):
        return "masked-background review"
    if any(token in lower for token in ("xy", "distort", "drift", "grid")):
        return "xy-distortion review"
    return "operator-corrected review"


def _original_for(target: Path, all_files: list[Path]) -> Path | None:
    """Find the one untouched sibling denoted by a corrected filename."""
    match = CORRECTED.search(target.name)
    if not match:
        return None
    prefix = target.name[:match.start()].strip()
    direct = target.with_name(prefix)
    if direct.is_file() and direct != target:
        return direct
    candidates = [path for path in all_files if path != target
                  and path.parent == target.parent
                  and (path.name == prefix or path.stem == prefix)]
    return candidates[0] if len(candidates) == 1 else None


def collect(root: Path, out: Path) -> dict:
    """Copy unambiguous original/target pairs to a blind, portable set."""
    if out.exists():
        raise ValueError(f"refusing to reuse output folder: {out}")
    all_files = [path for path in root.rglob("*") if path.is_file()]
    targets = sorted(path for path in all_files if CORRECTED.search(path.name))
    out.mkdir(parents=True)
    pairs, skipped = [], []
    for target in targets:
        original = _original_for(target, all_files)
        if original is None:
            skipped.append({"target": target.name, "reason": "no unique original"})
            continue
        ordinal = len(pairs) + 1
        suffix = original.suffix.lower()
        if not suffix:
            skipped.append({"target": target.name, "reason": "original has no suffix"})
            continue
        source_copy = out / f"source-{ordinal:03d}{suffix}"
        target_copy = out / f"corrected-{ordinal:03d}{suffix}"
        shutil.copy2(original, source_copy)
        shutil.copy2(target, target_copy)
        pairs.append({
            "ordinal": ordinal,
            "source": source_copy.name,
            "corrected": target_copy.name,
            "format": suffix.lstrip("."),
            "operator_hint": _operator_hint(target.name),
        })
    manifest = {"pairs": pairs, "skipped": skipped}
    (out / "targets.json").write_text(json.dumps(manifest, indent=2),
                                        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="folder containing originals and corrected copies")
    parser.add_argument("--out", type=Path, required=True, help="new blind target folder")
    args = parser.parse_args()
    manifest = collect(args.root, args.out)
    print(f"Collected {len(manifest['pairs'])} target pair(s); "
          f"skipped {len(manifest['skipped'])} ambiguous file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
