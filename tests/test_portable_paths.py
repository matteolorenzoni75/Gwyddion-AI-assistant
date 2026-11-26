from pathlib import Path
import pytest
from afm_copilot import paths


def test_legacy_layout_and_preference(tmp_path):
    home = tmp_path / 'AFM_Copilot'
    old = tmp_path / 'AFM_Automation'
    raw = old / 'All AFM Data'
    learning = old / 'OLD input IMAGES'
    raw.mkdir(parents=True)
    learning.mkdir()
    assert paths.default_locations(home) == (raw, learning)
    renamed = old / 'learning input data'
    learning.rename(renamed)
    assert paths.default_locations(home) == (raw, renamed)
    assert paths.locations({'raw': str(tmp_path)}, home)[0] == tmp_path


def test_reference_only_known_prefix(tmp_path):
    home = tmp_path / 'AFM_Copilot'
    learning = tmp_path / 'Learning'
    (learning / 'sample').mkdir(parents=True)
    ref = learning / 'sample' / 'scan.gwy'
    ref.write_bytes(b'raw')
    stale = home / 'data' / 'OLD input IMAGES' / 'sample' / 'scan.gwy'
    assert paths.resolve_reference(stale, home=home, learning=learning) == ref
    unknown = tmp_path / 'unrelated' / 'sample' / 'scan.gwy'
    assert paths.resolve_reference(unknown, home=home, learning=learning) == unknown
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b'existing')
    assert paths.resolve_reference(stale, home=home, learning=learning) == stale
    assert ref.read_bytes() == b'raw'


def test_save_optional_and_validation(tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    settings = tmp_path / 'private' / 'settings.json'
    paths.save_settings(raw, None, path=settings)
    assert paths._read_settings(settings)['learning'] is None
    assert paths.locations(paths._read_settings(settings), tmp_path)[0] == raw
    with pytest.raises(FileNotFoundError):
        paths.save_settings(tmp_path / 'missing', None, path=settings)
    assert paths._read_settings(settings)['raw'] == str(raw)


def test_preserve_original_row(monkeypatch, tmp_path):
    old = {'original': 'missing.gwy', 'manual': 'manual.gwy', 'automated': None, 'notes': 'x'}
    monkeypatch.setattr(paths, 'resolve_reference', lambda v: tmp_path / v)
    result = paths.reconcile_rows([old])
    assert result[0]['original'] == str(tmp_path / 'missing.gwy')
    assert result[0]['automated'] is None
    assert old['original'] == 'missing.gwy'
