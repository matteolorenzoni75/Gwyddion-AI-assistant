"""Filesystem layout is centralized under one AFM Copilot root."""
from pathlib import Path

import afm_copilot.paths as paths
import afm_copilot.directory_map as directory_map
import afm_copilot.archive_organizer as archive_organizer
import afm_copilot.labeler as labeler


def test_workspace_and_data_paths_share_single_root():
    assert paths.DATA_ROOT.parent == paths.HOME
    assert paths.WORKSPACE.parent == paths.HOME
    assert paths.LEGACY_ROOT.parent == paths.HOME
    assert paths.RAW_ARCHIVE.parent == paths.DATA_ROOT
    assert paths.HISTORICAL_RAW.parent == paths.DATA_ROOT


def test_consumers_use_centralized_paths():
    assert directory_map.WORKSPACE == paths.WORKSPACE
    assert directory_map.RAW_ARCHIVE == paths.RAW_ARCHIVE
    assert archive_organizer.DEFAULT_ROOT == paths.RAW_ARCHIVE
    assert labeler.DEFAULT_FOLDER == paths.HISTORICAL_RAW


def test_workspace_names_are_compact():
    names = {folder for _key, folder, _description in directory_map.WORKSPACE_FOLDERS}
    assert names == {"runs", "approved", "reports", "benchmark"}
