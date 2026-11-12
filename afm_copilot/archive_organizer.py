"""Local AFM archive organizer: inspect repeats, safely flatten nested folders.

Default is PREVIEW. --apply moves files (not copies) only after explicit
confirmation; originals are never overwritten or silently deduplicated.
All paths, hashes and recovery journal are strictly PRIVATE outside Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from afm_copilot.feedback import PROJECT_ROOT
from afm_copilot.labeling import DEFAULT_DB, FORMATS
from afm_copilot.paths import RAW_ARCHIVE

DEFAULT_ROOT = RAW_ARCHIVE
PRIVATE = Path.home() / "AFM_Copilot_Private_Audits" / "archive_organizer"
# Add common sidecars too. Never discard metadata by flattening only scans.
SCAN_EXTENSIONS = FORMATS
_SKIP = frozenset({".git", "$RECYCLE.BIN", "System Volume Information"})
# Conservative filename rule: candidates, never proof of same field of view.
_REPEAT = re.compile(
    r"(?i)(?:[\s_.-]+(?:copy|duplicate|rep|repeat|scan|image|img)"
    r"[\s_.-]*\d+|[\s_.-]+\(\d+\))+$")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _outside_root(root: Path, private: Path) -> None:
    rp = root.expanduser().resolve()
    pp = private.expanduser().resolve()
    git = PROJECT_ROOT.resolve()
    if pp == rp or rp in pp.parents or pp == git or git in pp.parents:
        raise ValueError("Private report must be outside source and Git repository")


def _list_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError("AFM archive folder does not exist")
    files = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        here = Path(directory)
        dirs[:] = sorted(
            d for d in dirs if d not in _SKIP and not (here / d).is_symlink()
        )
        for name in sorted(names):
            item = here / name
            if item.is_file() and not item.is_symlink():
                files.append(item)
    return sorted(files, key=lambda p: str(p.relative_to(root)).casefold())


def _destination(root: Path, source: Path, reserved: set[str]) -> Path:
    if source.parent == root:
        return source
    # Prefix with relative subfolder components for provenance and name safety.
    relative = source.relative_to(root)
    basename = "__".join(relative.parts)
    # A Windows component cannot exceed roughly 255 characters.
    if len(basename) > 170:
        suffix = hashlib.sha256(str(relative).encode("utf-8")).hexdigest()[:16]
        basename = basename[:140] + "__" + suffix + source.suffix
    trial = basename
    attempt = 0
    while trial.casefold() in reserved or (root / trial).exists():
        attempt += 1
        suffix = hashlib.sha256(
            (str(relative) + ":" + str(attempt)).encode("utf-8")).hexdigest()[:12]
        trial = basename[:140] + "__" + suffix + source.suffix
    reserved.add(trial.casefold())
    return root / trial


def build_plan(root: Path) -> dict:
    root = root.expanduser().resolve()
    files = _list_files(root)
    reserved = {f.name.casefold() for f in files if f.parent == root}
    entries = []
    by_hash = defaultdict(list)
    by_hint = defaultdict(list)
    for source in files:
        relative = source.relative_to(root)
        destination = _destination(root, source, reserved)
        stat = source.stat()
        # Hash every item, including instrument sidecars; never silently corrupt metadata.
        sha = _hash_file(source)
        row = {
            "source": str(source), "destination": str(destination),
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": sha, "is_scan": source.suffix.lower() in SCAN_EXTENSIONS,
            "move": source != destination,
        }
        entries.append(row)
        if row["is_scan"]:
            by_hash[sha].append(row)
            hint = _REPEAT.sub("", source.stem.casefold()).strip(" ._-")
            if len(hint) >= 3:
                by_hint[hint].append(row)
    duplicate_groups = [g for g in by_hash.values() if len(g) > 1]
    possible_series = [g for g in by_hint.values()
                       if len(g) > 1 and len({r["sha256"] for r in g}) > 1]
    return {
        "schema_version": 1, "root": str(root), "created": int(time.time()),
        "entries": entries,
        "summary": {
            "total_files": len(files),
            "afm_scans": sum(r["is_scan"] for r in entries),
            "files_to_move": sum(r["move"] for r in entries),
            "exact_duplicate_groups": len(duplicate_groups),
            "exact_duplicate_extra_copies": sum(len(g) - 1 for g in duplicate_groups),
            "possible_repeat_series": len(possible_series),
            "potential_series_members": sum(len(g) for g in possible_series),
            "non_afm_sidecars_kept": sum(not r["is_scan"] for r in entries),
            "trace_retrace_preserved": True,
            "duplicate_files_preserved": True,
            "original_bytes_unchanged": True,
            "warning": ("Repeated filename stems are only *candidates* for repeated "
                        "scans; similarity of actual topography is not yet verified. "
                        "Nothing is deleted, even exact duplicates."),
        },
    }


def _report_path() -> Path:
    return PRIVATE / "PRIVATE_flatten_plan.json"


def save_plan(plan: dict, destination: Path) -> None:
    _outside_root(Path(plan["root"]), destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    tmp.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    os.replace(tmp, destination)


def execute_plan(plan: dict, *, expected_root: Path, journal: Path) -> dict:
    """Moves verified files. Idempotent after interruption; never overwrites."""
    root = Path(plan["root"]).resolve()
    # Do not silently break the absolute paths used by existing expert labels.
    if DEFAULT_DB.is_file():
        import sqlite3
        try:
            with sqlite3.connect(
                "file:" + DEFAULT_DB.as_posix() + "?mode=ro", uri=True
            ) as conn:
                known = conn.execute(
                    "SELECT s.path FROM scans s INNER JOIN labels l USING(scan_id)"
                ).fetchall()
            if any(
                (Path(name).resolve() == root or
                 root in Path(name).resolve().parents)
                for (name,) in known
            ):
                raise ValueError(
                    "Archive contains existing expert-labeled paths; "
                    "migrate the labeling index before moving files"
                )
        except sqlite3.Error as error:
            raise ValueError("Cannot verify private labeling index") from error
    if root != expected_root.expanduser().resolve():
        raise ValueError("The plan was generated for another archive")
    _outside_root(root, journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    moved = 0
    already = 0
    errors = 0
    # Append a durable record for each completed movement.
    with journal.open("a", encoding="utf-8") as out:
        for record in plan["entries"]:
            if not record["move"]:
                continue
            source, target = Path(record["source"]), Path(record["destination"])
            if target.parent != root or source == target or root not in source.parents:
                raise ValueError("Unsafe move in private manifest")
            if target.exists():
                # Resume only when the source no longer exists AND the
                # target matches the original recorded bytes.
                if not source.exists() and target.is_file() and (
                    target.stat().st_size == record["size"] and
                    (not record["sha256"] or _hash_file(target) == record["sha256"])
                ):
                    already += 1
                    continue
                errors += 1
                continue
            if not source.is_file() or source.is_symlink():
                errors += 1
                continue
            st = source.stat()
            if st.st_size != record["size"] or st.st_mtime_ns != record["mtime_ns"]:
                errors += 1
                continue
            if record["sha256"] and _hash_file(source) != record["sha256"]:
                errors += 1
                continue
            # Exclusive destination creation prevents overwrite. Same-volume
            # filesystem rename is atomic on Windows. Refuse crossing drives.
            if source.drive.casefold() != target.drive.casefold():
                raise ValueError("Moves across volumes are not supported")
            os.rename(source, target)
            if target.stat().st_size != record["size"] or (
                record["sha256"] and _hash_file(target) != record["sha256"]
            ):
                raise OSError("Post-move verification failed: stop and inspect archive")
            out.write(json.dumps({"source": str(source), "destination": str(target),
                                  "size": record["size"]}) + "\n")
            out.flush()
            os.fsync(out.fileno())
            moved += 1

    # Only remove directories now empty; keep any folders containing
    # unknown/symlinked/unmoved files. No recursive deletion.
    removed_dirs = 0
    for directory, dirs, filenames in os.walk(root, topdown=False, followlinks=False):
        path = Path(directory)
        if path == root or path.is_symlink():
            continue
        try:
            path.rmdir()
        except OSError:
            continue
        removed_dirs += 1
    return {
        "moved": moved, "already_moved": already,
        "blocked_or_changed": errors, "empty_subdirectories_removed": removed_dirs,
        "exact_duplicates_deleted": 0, "source_content_modified": False,
        "journal_saved_privately": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--apply", action="store_true",
                        help="EXPLICITLY move files into archive root and remove empty dirs")
    parser.add_argument("--confirm", default="",
                        help='Required for --apply: literal "FLATTEN"')
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    plan_path = _report_path()
    if args.apply:
        if args.confirm != "FLATTEN":
            parser.error("--apply requires --confirm FLATTEN")
        if not plan_path.is_file():
            parser.error("Run the preview first to create a private plan")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        try:
            result = execute_plan(
                plan, expected_root=root,
                journal=PRIVATE / "PRIVATE_flatten_journal.jsonl")
        except (OSError, ValueError) as error:
            print(json.dumps({"status": "stopped_safely",
                              "reason": type(error).__name__}))
            return 3
        print(json.dumps({"status": "apply_completed", **result}, indent=2))
        return 0 if result["blocked_or_changed"] == 0 else 4
    try:
        plan = build_plan(root)
        save_plan(plan, plan_path)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "preview_failed",
                          "reason": type(error).__name__}))
        return 2
    print(json.dumps({"status": "preview_only", **plan["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
