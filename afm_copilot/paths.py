"""Single source of truth for AFM Copilot filesystem locations.

All public/local working paths derive from AFM_COPILOT_HOME. Private audit
material remains under the user's profile so it stays outside the Git checkout
and can be preserved independently of app moves.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("AFM_COPILOT_HOME", r"C:\AFM_Copilot")).expanduser()

APP_ROOT = HOME / "app"
DATA_ROOT = HOME / "data"
WORKSPACE = HOME / "workspace"
LEGACY_ROOT = HOME / "legacy"

RAW_ARCHIVE = DATA_ROOT / "All AFM Data"
HISTORICAL_RAW = DATA_ROOT / "OLD input IMAGES"
MANUAL_DATA = DATA_ROOT / "corrected"
PROCESSED_DATA = DATA_ROOT / "processed"

PRIVATE_ROOT = Path.home() / "AFM_Copilot_Private_Audits"
