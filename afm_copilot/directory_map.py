"""Local AFM directory map: where raw, manual, automatic and labels live.

Reads only known locations and existing PRIVATE manifests; never walks the
97k-file archive, hashes files, moves folders or changes Git. Exact private
paths are written only outside the public checkout; stdout is aggregate.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from afm_copilot.feedback import PROJECT_ROOT
from afm_copilot.labeling import DEFAULT_DB
from afm_copilot.manual_pairs import PRIVATE_ROOT as MANUAL_PRIVATE

RAW_ARCHIVE = Path(r"C:\AFM_Automation\All AFM Data")
EARLIER_RAW = Path(r"C:\AFM_Automation\OLD input IMAGES")
MANUAL_PAIR_MANIFEST = MANUAL_PRIVATE / "PRIVATE_manual_pair_candidates.json"
GUI_RESULTS = Path(tempfile.gettempdir()) / "afm_copilot_gui" / "processed" / "processed"
PRIVATE_OUT = Path.home() / "AFM_Copilot_Private_Audits" / "directory_map" / "PRIVATE_locations.json"
WORKSPACE = Path(r"C:\AFM_Automation\AFM_Copilot_Workspace")
WORKSPACE_FOLDERS = (
    ("pending_review", "01_Manual_To_Review", "Correzioni manuali da validare"),
    ("automatic", "02_Automatic_Results", "Nuove correzioni generate da AFM Copilot"),
    ("approved", "03_Approved", "Versioni approvate dall'operatore"),
    ("reports", "04_Reports", "Comparazioni e report di qualita"),
)


# Categories, not a promise that all data resides in these directories.
LOCATIONS = (
    ("raw_archive", "Archivio originale AFM", RAW_ARCHIVE,
     "97.082 file nell'ultimo inventario; non modificare la struttura adesso."),
    ("historical_raw", "Originali usati per le prove", EARLIER_RAW,
     "Scansioni storiche e candidate per confronti originali/manuali."),
    ("gui_processed", "Correzioni automatiche della GUI", GUI_RESULTS,
     "Derivati salvati dalla GUI attuale, se già elaborati."),
    ("manual_index", "Indice correzioni manuali", MANUAL_PAIR_MANIFEST,
     "Elenco privato degli abbinamenti trovati; non contiene immagini."),
    ("expert_database", "Database labeling esperto", DEFAULT_DB,
     "SQLite privato: non cancellare o spostare."),
    ("workspace", "Area di lavoro AFM Copilot", WORKSPACE,
     "Cartelle separate per correzioni automatiche, revisioni e approvazioni."),
    ("workspace_auto", "Output automatici organizzati", WORKSPACE / "02_Automatic_Results",
     "Destinazione per nuovi risultati: non copia quelli storici."),
    ("workspace_approved", "Correzioni approvate", WORKSPACE / "03_Approved",
     "Cartella dedicata ai risultati approvati dall'utente."),
    ("repo", "Codice AFM Copilot", PROJECT_ROOT,
     "Codice, test e strumenti; non è l'archivio delle immagini."),
)


def _manual_pairs() -> list[dict]:
    if not MANUAL_PAIR_MANIFEST.is_file():
        return []
    try:
        contents = json.loads(MANUAL_PAIR_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return contents.get("pairs", []) if isinstance(contents.get("pairs"), list) else []


def build_map(*, entries=LOCATIONS, pairs=None) -> dict:
    """Inventory only roots and already-known pair paths; no recursive scans."""
    pairs = _manual_pairs() if pairs is None else pairs
    locations = [{
        "key": key, "title": title, "path": str(path),
        "exists": path.exists(), "is_directory": path.is_dir(),
        "description": description,
    } for key, title, path, description in entries]
    manual_dirs = Counter()
    originals_missing = 0
    manual_missing = 0
    automatic_known = 0
    for row in pairs:
        if not isinstance(row, dict):
            continue
        original = row.get("original")
        manual = row.get("manual")
        if original and not Path(original).is_file():
            originals_missing += 1
        if manual:
            p = Path(manual)
            manual_dirs[str(p.parent)] += 1
            if not p.is_file():
                manual_missing += 1
        if row.get("automated"):
            automatic_known += 1
    return {
        "schema_version": 1,
        "locations": locations,
        "manual_correction_folders": [
            {"path": path, "candidate_pairs": n,
             "exists": Path(path).is_dir()}
            for path, n in sorted(manual_dirs.items())
        ],
        "summary": {
            "known_locations": len(locations),
            "existing_locations": sum(item["exists"] for item in locations),
            "manual_pairs_recorded": len(pairs),
            "manual_folders": len(manual_dirs),
            "manual_images_missing": manual_missing,
            "original_images_missing": originals_missing,
            "automatic_results_associated": automatic_known,
            "full_archive_rescanned": False,
            "source_files_modified": False,
        },
    }


def save_private(report: dict, destination: Path = PRIVATE_OUT) -> None:
    path = destination.expanduser().resolve()
    git = PROJECT_ROOT.resolve()
    archive = RAW_ARCHIVE.resolve()
    if path == git or git in path.parents or path == archive or archive in path.parents:
        raise ValueError("Private map must be stored outside source and Git")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def prepare_workspace(root: Path = WORKSPACE) -> dict:
    """Create empty workflow folders only; never move/copy image contents."""
    destination = root.expanduser().resolve()
    git = PROJECT_ROOT.resolve()
    archive = RAW_ARCHIVE.resolve()
    source = EARLIER_RAW.resolve()
    private = PRIVATE_OUT.parent.parent.resolve()
    for protected in (git, archive, source, private):
        if destination == protected or protected in destination.parents or destination in protected.parents:
            raise ValueError("Workspace must be separate from AFM raw and private source roots")
    created = 0
    for _key, folder, _description in WORKSPACE_FOLDERS:
        path = destination / folder
        if not path.exists():
            path.mkdir(parents=True, exist_ok=False)
            created += 1
        elif not path.is_dir() or path.is_symlink():
            raise ValueError("Workspace destination exists but is not a normal folder")
    return {
        "workspace_prepared": True, "folders_created": created,
        "folders_total": len(WORKSPACE_FOLDERS),
        "source_files_moved": 0, "source_files_deleted": 0,
        "raw_archive_scanned": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-workspace", action="store_true",
                        help="create separate EMPTY review/auto/approved/report folders; no scans moved")
    parser.add_argument("--private-report", action="store_true",
                        help="Print private report location, NOT file paths within it")
    args = parser.parse_args(argv)
    extra = prepare_workspace() if args.prepare_workspace else {}
    report = build_map()
    save_private(report)
    print(json.dumps({**report["summary"], **extra}, indent=2))
    if args.private_report:
        print("Detailed private map saved outside Git checkout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
