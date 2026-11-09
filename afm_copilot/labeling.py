"""Private, expandable AFM labeling catalogue (no automatic model fitting).

SQLite database is kept outside the public Git checkout. The operator may
label original TIFF, Igor Binary and .gwy scans without modifying them.
Rows can be added across sessions, folders and acquisition days.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from afm_copilot.feedback import PROJECT_ROOT

DEFAULT_DB = Path.home() / "AFM_Copilot_Private_Audits" / "labeling" / "labels.sqlite3"
FORMATS = frozenset({".ibw", ".tif", ".tiff", ".gwy", ".spm", ".jpk", ".sxm", ".nid", ".mi"})
FAMILIES = ("unclassified", "granular_continuous", "isolated_objects",
            "terraces", "pores", "fibres", "periodic", "flat_smooth",
            "rough_irregular", "mixed", "uncertain")
ARTIFACTS = ("tilt", "bow", "row_banding", "line_scars", "spikes",
             "periodic_noise", "drift", "feedback", "double_tip",
             "charging", "other")
ROLES = ("unassigned", "train", "validation", "holdout")
QUALITIES = ("unknown", "usable", "review", "reject")


def _outside_checkout(path: Path) -> None:
    p = path.expanduser().resolve()
    root = PROJECT_ROOT.resolve()
    if p == root or root in p.parents:
        raise ValueError("Label database must remain outside the public Git checkout")


def _connection(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    db = Path(db_path).expanduser().resolve()
    _outside_checkout(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS scans (
        scan_id INTEGER PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        bytes INTEGER NOT NULL,
        modified_ns INTEGER NOT NULL,
        sha256 TEXT,
        acquired_group TEXT NOT NULL DEFAULT '',
        imported_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS labels (
        scan_id INTEGER PRIMARY KEY REFERENCES scans(scan_id),
        family TEXT NOT NULL,
        artifacts_json TEXT NOT NULL,
        quality TEXT NOT NULL,
        confidence INTEGER NOT NULL,
        sample_group TEXT NOT NULL,
        dataset_role TEXT NOT NULL,
        notes TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
    """)
    return conn


def discover(folder: str | Path) -> list[Path]:
    """Find AFM scans recursively without following symlink directories."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    files = []
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
        for name in sorted(names):
            path = Path(current) / name
            if path.suffix.lower() in FORMATS and path.is_file() and not path.is_symlink():
                files.append(path.resolve())
    return sorted(set(files), key=lambda p: str(p).casefold())


def register_folder(folder: str | Path, db_path: str | Path = DEFAULT_DB) -> dict:
    """Idempotent import: never erase or overwrite existing human labels."""
    found = discover(folder)
    count_new = 0
    stamp = datetime.now(timezone.utc).isoformat()
    with _connection(db_path) as conn:
        for path in found:
            stat = path.stat()
            cursor = conn.execute(
                "INSERT OR IGNORE INTO scans (path,bytes,modified_ns,imported_at)"
                " VALUES (?,?,?,?)",
                (str(path), stat.st_size, stat.st_mtime_ns, stamp))
            count_new += cursor.rowcount
        total = conn.execute("SELECT count(*) FROM scans").fetchone()[0]
    return {"found": len(found), "added": count_new, "total": total}


def get_scans(db_path: str | Path = DEFAULT_DB) -> list[dict]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT s.*, l.family, l.artifacts_json, l.quality, l.confidence,"
            " l.sample_group, l.dataset_role, l.notes, l.updated_at"
            " FROM scans s LEFT JOIN labels l USING (scan_id)"
            " ORDER BY s.scan_id").fetchall()
        result = [dict(r) for r in rows]
    for row in result:
        row["artifacts"] = json.loads(row.pop("artifacts_json")) if row["artifacts_json"] else []
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_label(scan_id: int, *, family: str, artifacts: list[str],
               quality: str, confidence: int, sample_group: str,
               dataset_role: str, notes: str = "",
               db_path: str | Path = DEFAULT_DB) -> dict:
    """Save one operator label; enforce sample-group-level split isolation."""
    if family not in FAMILIES or quality not in QUALITIES or dataset_role not in ROLES:
        raise ValueError("Unknown label option")
    if any(x not in ARTIFACTS for x in artifacts):
        raise ValueError("Unknown artifact")
    if not isinstance(confidence, int) or not 1 <= confidence <= 5:
        raise ValueError("Confidence must be 1-5")
    group = sample_group.strip()
    if len(group) > 150 or len(notes) > 3000:
        raise ValueError("Group or notes too long")
    if dataset_role != "unassigned" and not group:
        raise ValueError("Sample/group ID is required before assigning a split")
    # Never let an uncertain/unclassified entry be an eligible training label.
    if family in ("unclassified", "uncertain") and dataset_role == "train":
        raise ValueError("Uncertain scans cannot be assigned to training")
    now = datetime.now(timezone.utc).isoformat()
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
        if row is None:
            raise KeyError("Scan is not registered")
        path = Path(row["path"])
        if not path.is_file():
            raise FileNotFoundError("Original scan is missing")
        stat = path.stat()
        digest = _sha256(path)
        # A changed original gets a new state for review; never silently reuse a label.
        prior = conn.execute("SELECT * FROM labels WHERE scan_id=?", (scan_id,)).fetchone()
        if prior and row["sha256"] and digest != row["sha256"]:
            raise ValueError("Source bytes have changed since labeling; re-import separately")
        if dataset_role != "unassigned":
            conflicts = conn.execute(
                "SELECT DISTINCT l.dataset_role FROM labels l "
                "WHERE l.sample_group=? AND l.dataset_role!='unassigned' "
                "AND l.scan_id!=?", (group, scan_id)).fetchall()
            if any(r[0] != dataset_role for r in conflicts):
                raise ValueError("Same specimen/session already belongs to another dataset split")
        conn.execute("UPDATE scans SET bytes=?, modified_ns=?, sha256=? WHERE scan_id=?",
                     (stat.st_size, stat.st_mtime_ns, digest, scan_id))
        conn.execute(
            "INSERT INTO labels (scan_id,family,artifacts_json,quality,confidence,"
            "sample_group,dataset_role,notes,updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(scan_id) DO UPDATE SET "
            "family=excluded.family,artifacts_json=excluded.artifacts_json,"
            "quality=excluded.quality,confidence=excluded.confidence,"
            "sample_group=excluded.sample_group,dataset_role=excluded.dataset_role,"
            "notes=excluded.notes,updated_at=excluded.updated_at",
            (scan_id, family, json.dumps(sorted(set(artifacts))), quality,
             confidence, group, dataset_role, notes.strip(), now))
    return {"scan_id": scan_id, "saved": True, "dataset_role": dataset_role}


def counts(db_path: str | Path = DEFAULT_DB) -> dict:
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT s.sha256, l.dataset_role, l.family FROM scans s "
            "LEFT JOIN labels l USING(scan_id)").fetchall()
    roles = {role: 0 for role in ROLES}
    roles["unlabeled"] = 0
    for row in rows:
        if row["family"] is None:
            roles["unlabeled"] += 1
        else:
            roles[row["dataset_role"]] += 1
    return {"total": len(rows), "labeled": len(rows) - roles["unlabeled"],
            "roles": roles, "model_trained": False}


def safe_summary(db_path: str | Path = DEFAULT_DB) -> dict:
    """Only aggregate statistics are safe to share, never file paths or notes."""
    return counts(db_path)
