"""Portable local paths. Configuration is private; raw data is never moved."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("AFM_COPILOT_HOME", str(PROJECT_ROOT))).expanduser().resolve()
DATA_ROOT = HOME / "data"
APP_ROOT = PROJECT_ROOT
WORKSPACE = HOME / "workspace"
LEGACY_ROOT = HOME / "legacy"
PRIVATE_ROOT = Path.home() / "AFM_Copilot_Private_Audits"
SETTINGS = PRIVATE_ROOT / "settings.json"


def _read_settings(path: Path = SETTINGS) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("AFM settings must be a JSON object")
    return data


def _existing(candidates):
    return next((p for p in candidates if p.is_dir()), candidates[0])


def default_locations(home: Path = HOME) -> tuple[Path, Path]:
    data = home / "data"
    old = home.parent / "AFM_Automation"
    return (_existing([old / "All AFM Data", data / "All AFM Data"]),
            _existing([old / "learning input data", old / "OLD input IMAGES",
                       data / "learning input data", data / "OLD input IMAGES"]))


def locations(settings: dict, home: Path = HOME) -> tuple[Path, Path]:
    raw, learning = default_locations(home)
    if settings.get("raw"):
        raw = Path(settings["raw"]).expanduser()
    if settings.get("learning"):
        learning = Path(settings["learning"]).expanduser()
    elif "learning" in settings:
        learning = home / "data" / "learning input data"
    return raw, learning


def save_settings(raw: Path, learning: Path | None, *, path: Path = SETTINGS) -> None:
    raw = raw.expanduser().resolve(strict=True)
    if not raw.is_dir():
        raise ValueError("Choose an existing AFM data folder")
    if learning is not None:
        learning = learning.expanduser().resolve(strict=True)
        if not learning.is_dir():
            raise ValueError("Choose an existing learning folder")
    for source in (raw, learning):
        if source is None:
            continue
        for protected in (WORKSPACE.resolve(), PRIVATE_ROOT.resolve()):
            if source == protected or source in protected.parents or protected in source.parents:
                raise ValueError("Data folders must not overlap generated output or private state")
        if source == PROJECT_ROOT or source in PROJECT_ROOT.parents:
            raise ValueError("Choose a data folder, not the software checkout")
    path = path.expanduser().resolve()
    if path == PROJECT_ROOT or PROJECT_ROOT in path.parents:
        raise ValueError("Settings must stay outside the Git checkout")
    data = _read_settings(path)
    data.update(schema_version=1, raw=str(raw), learning=str(learning) if learning else None)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


CONFIG = _read_settings()
RAW_ARCHIVE, HISTORICAL_RAW = locations(CONFIG)
LEARNING_ENABLED = CONFIG.get("learning", True) is not None
MANUAL_DATA = DATA_ROOT / "corrected"
PROCESSED_DATA = DATA_ROOT / "processed"
BLIND_INPUT = HOME / "manual_review" / "blind_input"
MANUAL_CORRECTED = HOME / "manual_review" / "manual_corrected"


def resolve_reference(value: str | Path, *, home: Path = HOME,
                      learning: Path | None = None) -> Path:
    """Repair only known historic learning paths, preserving the entire suffix.

    Never match just a basename, never search the raw archive, and never replace
    a path that already exists. A new configured dataset is not presumed to be
    a relocation of the old dataset.
    """
    original = Path(value).expanduser()
    if original.is_file():
        return original
    aliases = [home / "data" / "OLD input IMAGES", home / "data" / "learning input data",
               home.parent / "AFM_Automation" / "OLD input IMAGES",
               home.parent / "AFM_Automation" / "learning input data"]
    candidates = [learning] if learning is not None else aliases
    matches = {}
    for alias in aliases:
        try:
            suffix = original.relative_to(alias)
        except ValueError:
            continue
        for folder in candidates:
            target = folder / suffix
            if target.is_file():
                matches[target.resolve()] = target
    return next(iter(matches.values())) if len(matches) == 1 else original


def reconcile_rows(rows: list[dict]) -> list[dict]:
    result = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        for key in ("original", "manual", "automated"):
            if row.get(key):
                row[key] = str(resolve_reference(row[key]))
        result.append(row)
    return result
