@echo off
setlocal EnableExtensions DisableDelayedExpansion
title AFM Copilot - install or update and verify
cd /d "%TEMP%"
echo AFM Copilot permanent installer / updater.
echo Close AFM Copilot before updating. No AFM images will be moved or copied.
set "AFM_SCRIPT=%~f0"
set "ROOT=C:\AFM_Copilot"
if defined AFM_COPILOT_HOME set "ROOT=%AFM_COPILOT_HOME%"
if exist "%~dp0.git" set "ROOT=%~dp0"
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "PYCODE=import os,sys; p=os.environ['AFM_SCRIPT']; s=open(p,encoding='utf-8').read(); sys.argv=[p,p]; exec(compile(s.split('#'+'===PYTHON===',1)[1],p,'exec'))"
if exist "%PY%" goto runvenv
where py.exe >nul 2>nul
if not errorlevel 1 (
  py -3.11 -c "import sys; assert sys.version_info[:2]==(3,11)" >nul 2>nul
  if not errorlevel 1 goto runpy
)
where python.exe >nul 2>nul
if not errorlevel 1 (
  python.exe -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
  if not errorlevel 1 goto runpython
)
where winget.exe >nul 2>nul
if errorlevel 1 goto missing
echo Installing Python 3.11 via Windows Package Manager...
winget install --id Python.Python.3.11 --exact --source winget --accept-source-agreements --accept-package-agreements
set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if exist "%PY%" goto runvenv
set "PY=%ProgramFiles%\Python311\python.exe"
if exist "%PY%" goto runvenv
goto missing
:runvenv
"%PY%" -B -c "%PYCODE%"
goto done
:runpy
py -3.11 -B -c "%PYCODE%"
goto done
:runpython
python.exe -B -c "%PYCODE%"
goto done
:missing
echo Python 3.11 not available. Install Python, then rerun this same installer.
pause
exit /b 2
:done
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo Setup stopped. Read the error above; your AFM data was not touched.
pause
exit /b %RC%
#===PYTHON===
"""Permanent AFM setup/update. Only Git-tracked software is updated."""
from __future__ import annotations
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_URL = 'https://github.com/matteolorenzoni75/Gwyddion-AI-assistant.git'
BRANCH = 'dev/manual-gold-set'
GENERATED = {'AFM Copilot.bat', '.gitignore', 'AFM_SETUP.cmd'}


def git(root, *args, check=True, data=None):
    proc = subprocess.run(['git', '-C', str(root), *args], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode:
        raise RuntimeError(proc.stderr.decode('utf-8', 'replace').strip() or str(args))
    return proc


def names(proc):
    return {p.decode('utf-8') for p in proc.stdout.split(b'\0') if p}


def merge_text(base, local, incoming):
    if any(b'\0' in v for v in (base, local, incoming)):
        raise RuntimeError('Binary source conflict')
    # Git blobs are typically LF while a Windows working tree may be CRLF.
    crlf = b'\r\n' in local and b'\n' not in local.replace(b'\r\n', b'')
    base, local, incoming = (v.replace(b'\r\n', b'\n') for v in (base, local, incoming))
    def eol(value):
        return value.replace(b'\n', b'\r\n') if crlf else value
    if local == base:
        return eol(incoming)
    if incoming == base or local == incoming:
        return eol(local)
    with tempfile.TemporaryDirectory(prefix='afm-merge-') as d:
        folder = Path(d)
        for name, content in [('local', local), ('base', base), ('remote', incoming)]:
            (folder / name).write_bytes(content)
        p = subprocess.run(['git', 'merge-file', '-p', str(folder / 'local'),
                            str(folder / 'base'), str(folder / 'remote')], capture_output=True)
        if p.returncode != 0:
            raise RuntimeError('Overlapping source edits require review')
        return eol(p.stdout)


def update_to(root, target, private, branch=BRANCH):
    head = git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    target = git(root, 'rev-parse', target).stdout.decode().strip()
    if git(root, 'merge-base', '--is-ancestor', target, head, check=False).returncode == 0:
        print('Already contains requested version.', flush=True)
        return
    if git(root, 'merge-base', '--is-ancestor', head, target, check=False).returncode:
        raise RuntimeError('Local history has diverged. No automatic reset or force push.')
    if git(root, 'ls-files', '-u').stdout:
        raise RuntimeError('Resolve the existing Git merge conflict first.')
    dirty = names(git(root, 'diff', '--name-only', '-z', 'HEAD'))
    changed = names(git(root, 'diff', '--name-only', '-z', head, target))
    overlap = sorted(dirty & changed)
    staged = names(git(root, 'diff', '--cached', '--name-only', '-z'))
    originals, merged = {}, {}
    for name in overlap:
        path = root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError('Nonregular conflicting software path: ' + name)
        local = path.read_bytes()
        originals[name] = local
        if name in GENERATED:
            continue  # Remote launcher/ignore are canonical; local bytes are archived below.
        if name in staged:
            raise RuntimeError('Staged source change requires review: ' + name)
        base = git(root, 'show', f'{head}:{name}').stdout
        incoming = git(root, 'show', f'{target}:{name}').stdout
        try:
            merged[name] = merge_text(base, local, incoming)
        except RuntimeError as error:
            raise RuntimeError(f'{error}: {name}') from error
    current = git(root, 'branch', '--show-current').stdout.decode().strip()
    if current != branch:
        local_ref = git(root, 'rev-parse', '--verify', 'refs/heads/' + branch, check=False)
        if local_ref.returncode == 0:
            if local_ref.stdout.decode().strip() != head:
                raise RuntimeError('Local update branch has a different history; no files changed.')
            git(root, 'switch', branch)
        else:
            git(root, 'switch', '-c', branch)
    backup = None
    staged_patch = b''
    if overlap:
        backup = private / ('software-update-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        backup.mkdir(parents=True, exist_ok=False)
        for name, content in originals.items():
            dest = backup / 'files' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        staged_patch = git(root, 'diff', '--cached', '--binary', '--', *overlap).stdout
        (backup / 'staged.diff').write_bytes(staged_patch)
        (backup / 'worktree.diff').write_bytes(git(root, 'diff', '--binary', '--', *overlap).stdout)
        print('Only overlapping local software saved:', backup, flush=True)
    try:
        if overlap:
            git(root, 'restore', '--source=HEAD', '--staged', '--worktree', '--', *overlap)
        git(root, 'merge', '--ff-only', target)
    except Exception:
        if overlap and git(root, 'rev-parse', 'HEAD').stdout.decode().strip() == head:
            if staged_patch:
                git(root, 'apply', '--cached', '-', data=staged_patch)
            for name, content in originals.items():
                (root / name).write_bytes(content)
        raise
    for name, content in merged.items():
        (root / name).write_bytes(content)
    # Preserve additional local ignore exclusions, without local unignore rules
    # undoing the new repository protections. Never stage any private file.
    if '.gitignore' in originals:
        local = originals['.gitignore'].decode('utf-8-sig', 'replace').splitlines()
        extra = [line for line in local if line.strip() and not line.lstrip().startswith(('#', '!'))]
        exclude = Path(git(root, 'rev-parse', '--git-path', 'info/exclude').stdout.decode().strip())
        if not exclude.is_absolute():
            exclude = root / exclude
        exclude.parent.mkdir(parents=True, exist_ok=True)
        old = exclude.read_text(encoding='utf-8', errors='replace') if exclude.exists() else ''
        new = [line for line in extra if line not in old.splitlines()]
        if new:
            with exclude.open('a', encoding='utf-8') as stream:
                stream.write('\n# Local exclusions preserved by AFM setup\n' + '\n'.join(new) + '\n')
    print('Updated software:', git(root, 'rev-parse', '--short', 'HEAD').stdout.decode().strip(), flush=True)


def main():
    if os.name != 'nt':
        raise RuntimeError('This installer is intended for Windows')
    script = Path(sys.argv[1]).resolve()
    root = Path(os.environ.get('AFM_COPILOT_HOME', r'C:\AFM_Copilot'))
    if (script.parent / '.git').exists():
        root = script.parent
    root = root.resolve()
    if not root.exists() or (root.is_dir() and not any(root.iterdir())):
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--branch', BRANCH, REPO_URL, str(root)], check=True)
    else:
        top = Path(git(root, 'rev-parse', '--show-toplevel').stdout.decode().strip()).resolve()
        if top != root:
            raise RuntimeError('The selected project root is not an independent Git checkout')
        origin = git(root, 'remote', 'get-url', 'origin').stdout.decode().strip()
        normalized = origin.lower().replace('git@github.com:', 'https://github.com/').removesuffix('.git').rstrip('/')
        if normalized != REPO_URL.lower().removesuffix('.git'):
            raise RuntimeError('Unexpected Git origin. Existing checkout left unchanged.')
        target = 'refs/remotes/origin/' + BRANCH
        git(root, 'fetch', 'origin', 'refs/heads/' + BRANCH + ':' + target)
        update_to(root, target, Path.home() / 'AFM_Copilot_Private_Audits' / 'updates')
    launcher = root / 'AFM Copilot.bat'
    if not launcher.is_file():
        raise RuntimeError('Permanent launcher missing')
    # Run the permanent launcher in-place. No separate checkout, no data migration.
    command = f'""{launcher}" --verify"'
    result = subprocess.run(os.environ.get('COMSPEC', 'cmd.exe') + ' /d /s /c ' + command,
                            cwd=root)
    if result.returncode:
        print('Installation verification has failures. See diagnostic report; no code was pushed from this PC.', flush=True)
        return result.returncode
    print('Installation verified. Opening AFM Copilot.', flush=True)
    subprocess.Popen(os.environ.get('COMSPEC', 'cmd.exe') + f' /d /s /c ""{launcher}""', cwd=root)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
