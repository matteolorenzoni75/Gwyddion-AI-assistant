from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
NS = {"__name__": "setup_test"}
payload = (ROOT / "AFM_SETUP.cmd").read_text(encoding="utf-8").split("#===PYTHON===", 1)[1]
exec(compile(payload, "AFM_SETUP.cmd", "exec"), NS)


def test_windows_line_endings_merge():
    base = b'one\nline2\nline3\nline4\nfive\n'
    local = b'one\r\nline2\r\nline3\r\nline4\r\nFIVE\r\n'
    remote = b'ONE\nline2\nline3\nline4\nfive\n'
    assert NS["merge_text"](base, local, remote) == b'ONE\r\nline2\r\nline3\r\nline4\r\nFIVE\r\n'


def g(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True,
                                   stderr=subprocess.STDOUT).strip()


def setup_repo(tmp):
    repo = tmp / 'repo'
    repo.mkdir()
    g(repo, 'init', '-b', 'main')
    g(repo, 'config', 'user.email', 'test@example.org')
    g(repo, 'config', 'user.name', 'Test')
    g(repo, 'config', 'core.autocrlf', 'false')
    (repo / 'app.py').write_bytes(b'one\nline2\nline3\nline4\nfive\n')
    (repo / 'AFM Copilot.bat').write_bytes(b'old\n')
    (repo / '.gitignore').write_bytes(b'raw/\n')
    g(repo, 'add', '.')
    g(repo, 'commit', '-m', 'base')
    g(repo, 'switch', '-c', 'upstream')
    (repo / 'app.py').write_bytes(b'ONE\nline2\nline3\nline4\nfive\n')
    (repo / 'AFM Copilot.bat').write_bytes(b'new\n')
    (repo / '.gitignore').write_bytes(b'raw/\nworkspace/\n')
    g(repo, 'commit', '-am', 'upstream')
    g(repo, 'switch', 'main')
    return repo


def test_safe_update(tmp_path):
    repo = setup_repo(tmp_path)
    (repo / 'app.py').write_bytes(b'one\nline2\nline3\nline4\nFIVE\n')
    (repo / 'AFM Copilot.bat').write_bytes(b'local launcher\n')
    (repo / '.gitignore').write_bytes(b'raw/\nmy-private/\n')
    (repo / 'raw').mkdir()
    (repo / 'raw' / 'scan.ibw').write_bytes(b'data')
    NS["update_to"](repo, 'upstream', tmp_path / 'private', 'candidate')
    assert (repo / 'app.py').read_bytes() == b'ONE\nline2\nline3\nline4\nFIVE\n'
    assert (repo / 'AFM Copilot.bat').read_bytes() == b'new\n'
    assert (repo / 'raw' / 'scan.ibw').read_bytes() == b'data'
    assert 'my-private/' in (repo / '.git/info/exclude').read_text()
    assert list((tmp_path / 'private').glob('*/files/AFM Copilot.bat'))[0].read_bytes() == b'local launcher\n'
    NS["update_to"](repo, 'upstream', tmp_path / 'private', 'candidate')


def test_conflict_stops_before_changes(tmp_path):
    repo = setup_repo(tmp_path)
    (repo / 'app.py').write_bytes(b'LOCAL\nline2\nline3\nline4\nfive\n')
    head = g(repo, 'rev-parse', 'HEAD')
    with pytest.raises(RuntimeError, match='Overlapping source edits'):
        NS["update_to"](repo, 'upstream', tmp_path / 'private', 'candidate')
    assert g(repo, 'rev-parse', 'HEAD') == head
    assert (repo / 'app.py').read_bytes().startswith(b'LOCAL')
