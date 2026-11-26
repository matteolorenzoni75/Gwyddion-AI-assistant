"""Private manual reference workflow for an already anonymized AFM pool.

No archive traversal, automatic correction, source renaming or training.
Only the selected scan gets a private working copy for editing in Gwyddion.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from afm_copilot.paths import HOME, PRIVATE_ROOT, PROJECT_ROOT

DEFAULT_POOL = HOME / "manual_review" / "blind_input"
STATE_ROOT = PRIVATE_ROOT / "manual_gold_set"
FORMATS = frozenset({
    ".gwy", ".ibw", ".tif", ".tiff", ".spm", ".nid", ".mi",
    ".sxm", ".jpk", ".top", ".stp", ".afm", ".ezd", ".par",
})
BLIND_NAME = re.compile(r"AFM_[A-Z0-9]{8,32}", re.IGNORECASE)
DECISIONS = ("corrected", "no_change", "reject", "deferred")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def private_path(path: Path) -> Path:
    path = path.expanduser().resolve()
    checkout = PROJECT_ROOT.resolve()
    if path == checkout or checkout in path.parents:
        raise ValueError("Private gold-set state must be outside the Git checkout")
    return path


def discover(pool: Path) -> list[Path]:
    """Flat anonymous input folder ONLY; never descend into an archive."""
    pool = pool.expanduser().resolve()
    if not pool.is_dir():
        return []
    return sorted(
        p for p in pool.iterdir()
        if p.is_file() and not p.is_symlink()
        and p.suffix.lower() in FORMATS and BLIND_NAME.fullmatch(p.stem)
    )


def connection(db: Path | None = None) -> sqlite3.Connection:
    path = private_path(db or STATE_ROOT / "progress.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS reviews (
        review_id INTEGER PRIMARY KEY,
        source TEXT NOT NULL, source_hash TEXT NOT NULL,
        decision TEXT NOT NULL, reference TEXT, reference_hash TEXT,
        notes TEXT NOT NULL, at TEXT NOT NULL
    )""")
    conn.commit()
    return conn


def latest(source: Path, db: Path | None = None) -> dict | None:
    source = source.resolve()
    if not source.is_file():
        return None
    with connection(db) as conn:
        row = conn.execute(
            "SELECT * FROM reviews WHERE source=? ORDER BY review_id DESC LIMIT 1",
            (str(source),),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    if result["source_hash"] != sha256(source):
        return None
    if result["decision"] == "corrected":
        ref = Path(result["reference"])
        if not ref.is_file() or sha256(ref) != result["reference_hash"]:
            return None
    return result


def record(source: Path, decision: str, *, reference: Path | None = None,
           notes: str = "", db: Path | None = None,
           expected_source_hash: str | None = None) -> dict:
    """Append an explicit human decision; changing files invalidates the record."""
    source = source.resolve(strict=True)
    if decision not in DECISIONS:
        raise ValueError("Unknown review decision")
    if not source.is_file() or not BLIND_NAME.fullmatch(source.stem):
        raise ValueError("Expected an anonymized AFM input")
    source_hash = sha256(source)
    if expected_source_hash is not None and source_hash != expected_source_hash:
        raise ValueError("Input changed during review")
    ref = None
    ref_hash = None
    if decision == "corrected":
        if reference is None:
            raise ValueError("Select the manually corrected file")
        ref = reference.resolve(strict=True)
        if ref == source or not ref.is_file() or ref.suffix.lower() != ".gwy":
            raise ValueError("Save the correction as a separate Gwyddion .gwy file")
        ref_hash = sha256(ref)
        if ref_hash == source_hash:
            raise ValueError("Identical file: use No correction needed instead")
    elif reference is not None:
        raise ValueError("Only a corrected decision may contain a reference")
    at = datetime.now(timezone.utc).isoformat()
    with connection(db) as conn:
        conn.execute(
            "INSERT INTO reviews(source, source_hash, decision, reference, "
            "reference_hash, notes, at) VALUES (?,?,?,?,?,?,?)",
            (str(source), source_hash, decision, str(ref) if ref else None,
             ref_hash, notes, at),
        )
    return {"source": str(source), "source_hash": source_hash,
            "decision": decision, "reference": str(ref) if ref else None,
            "reference_hash": ref_hash, "notes": notes, "at": at}


def working_copy(source: Path, root: Path | None = None) -> Path:
    """Create one working copy on demand; never overwrite even an edited draft."""
    source = source.resolve(strict=True)
    root = private_path(root or STATE_ROOT / "editing")
    root.mkdir(parents=True, exist_ok=True)
    identity = sha256(source)
    folder = root / identity
    folder.mkdir(exist_ok=True)
    dest = folder / source.name
    if not dest.exists():
        with source.open("rb") as inp, dest.open("xb") as out:
            shutil.copyfileobj(inp, out)
        if sha256(dest) != identity:
            raise RuntimeError("Working copy could not be verified")
    return dest


def export_manifest(pool: Path, *, db: Path | None = None,
                    destination: Path | None = None) -> dict:
    """Export current human references, not a training set or a claim of truth."""
    destination = private_path(destination or STATE_ROOT / "PRIVATE_gold_pairs.json")
    rows, controls, rejected = [], [], []
    for source in discover(pool):
        review = latest(source, db)
        if not review:
            continue
        if review["decision"] == "corrected":
            rows.append({"original": str(source.resolve()),
                         "manual": review["reference"], "automated": None,
                         "source_sha256": review["source_hash"],
                         "manual_sha256": review["reference_hash"],
                         "notes": review["notes"]})
        elif review["decision"] == "no_change":
            controls.append(review)
        elif review["decision"] == "reject":
            rejected.append(review)
    payload = {"schema_version": 1, "pairs": rows,
               "no_change_controls": controls, "rejected": rejected,
               "source": "explicit_manual_gold_set_reviews",
               "training_performed": False, "private_only": True}
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Versioned export, so prior benchmark associations are never overwritten.
    if destination.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        destination = destination.with_name(destination.stem + "_" + stamp + ".json")
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
    return {"pairs": len(rows), "controls": len(controls),
            "rejected": len(rejected), "path": str(destination)}
