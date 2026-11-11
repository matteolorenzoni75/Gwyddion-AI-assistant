"""Maintenance never alters raw archives or private labels."""
from afm_copilot.maintenance import candidates, tidy


def test_safe_cache_preview_and_clean_only_known_temporary_directories(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    cache = root / "afm_copilot" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.pyc").write_bytes(b"compiled")
    private = root / "data" / "__pycache__"
    private.mkdir(parents=True)
    (private / "private-note").write_text("do not touch")
    source = root / "afm_copilot" / "module.py"
    source.write_text("hello")
    report = tidy(root=root)
    assert report["safe_cache_directories"] == 1
    assert source.exists() and cache.exists()
    assert private.exists()
    done = tidy(root=root, apply=True)
    assert done["safe_cache_directories_removed"] == 1
    assert not cache.exists()
    assert private.exists() and source.exists()
    assert done["raw_files_touched"] == 0
