"""Read-only inventory of labels stored by AFM Copilot.

Run: python -B tools/find_saved_labels.py

No filenames, scan names, notes or original image paths are printed.
The detailed location index is saved privately outside the Git checkout.
This tool does not import, migrate, edit or overwrite any labels.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from afm_copilot.labeling import DEFAULT_DB

PROJECT = Path(__file__).resolve().parent.parent
SEARCH_ROOTS = (
    Path.home() / "AFM_Copilot_Private_Audits",
    Path(r"C:\AFM_Automation\OLD input IMAGES"),
    Path(r"C:\AFM_Copilot"),
    Path(r"C:\AFM_image_wizard"),
)
REVIEW_NAME = ".afm-copilot-reviews.json"
DATABASE_NAME = "labels.sqlite3"
LEDGER_NAME = "operator_feedback.jsonl"
SKIP = frozenset({".git", ".venv", "node_modules", "__pycache__", "site-packages"})


def _scan_roots(roots):
    """Traverse known working folders only, not the entire disk."""
    visited = set()
    for base in roots:
        root = Path(base).expanduser()
        if not root.is_dir():
            continue
        for current, directories, filenames in os.walk(root, followlinks=False):
            here = Path(current)
            if here.is_symlink():
                directories[:] = []
                continue
            directories[:] = sorted(
                d for d in directories
                if d not in SKIP and not (here / d).is_symlink()
            )
            for name in sorted(filenames):
                if name not in (REVIEW_NAME, DATABASE_NAME, LEDGER_NAME):
                    continue
                path = here / name
                if not path.is_file() or path.is_symlink():
                    continue
                key = os.path.normcase(str(path.resolve()))
                if key not in visited:
                    visited.add(key)
                    yield path


def _sqlite_count(path):
    """Open with SQLite read-only URI so no database is ever created."""
    from urllib.parse import quote
    uri = "file:" + quote(str(path.resolve()).replace("\\", "/"), safe="/:") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"scans", "labels"}.issubset(tables):
            return {"status": "not_afm_labeler_database"}
        return {
            "status": "ok",
            "registered": connection.execute("SELECT COUNT(*) FROM scans").fetchone()[0],
            "labels": connection.execute("SELECT COUNT(*) FROM labels").fetchone()[0],
        }
    finally:
        connection.close()


def _review_count(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("reviews") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {"status": "unrecognized_format"}
    valid = [r for r in rows if isinstance(r, dict) and r.get("family")]
    return {"status": "ok", "reviews": len(valid)}


def _ledger_count(path):
    n = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                json.loads(line)  # Validate without exposing private content.
                n += 1
    return {"status": "ok", "events": n}


def locate(roots=SEARCH_ROOTS, *, private_report=None):
    """Return anonymized aggregates; keep exact locations private."""
    entries = []
    totals = Counter()
    for path in _scan_roots(roots):
        kind = ("review" if path.name == REVIEW_NAME else
                "database" if path.name == DATABASE_NAME else "feedback")
        try:
            summary = (
                _review_count(path) if kind == "review" else
                _sqlite_count(path) if kind == "database" else
                _ledger_count(path)
            )
        except (OSError, ValueError, sqlite3.Error, UnicodeError) as error:
            summary = {"status": "unreadable", "error_type": type(error).__name__}
        entries.append({"kind": kind, "path": str(path.resolve()), **summary})
        if summary["status"] == "ok":
            totals["review_entries"] += summary.get("reviews", 0)
            totals["database_labels"] += summary.get("labels", 0)
            totals["feedback_events"] += summary.get("events", 0)
        totals["sources_found"] += 1

    report = Path(private_report) if private_report else (
        Path.home() / "AFM_Copilot_Private_Audits" / "label_recovery" /
        "PRIVATE_locations.json"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    if PROJECT.resolve() == report.resolve() or PROJECT.resolve() in report.resolve().parents:
        raise ValueError("Recovery map must not be saved inside the Git project")
    report.write_text(json.dumps({
        "created_at": datetime.now().astimezone().isoformat(), "sources": entries
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "searched": "known AFM application folders only",
        "sources_found": totals["sources_found"],
        "review_entries": totals["review_entries"],
        "database_labels": totals["database_labels"],
        "feedback_events": totals["feedback_events"],
        "sources_by_type": dict(sorted(Counter(x["kind"] for x in entries).items())),
        "source_counts": [
            {k: value for k, value in entry.items()
             if k not in ("path", "error_type")}
            for entry in entries
        ],
        "private_report_saved": True,
        "no_labels_modified": True,
        "note": "No source file names, paths, or review notes are printed.",
    }


def main():
    print(json.dumps(locate(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
