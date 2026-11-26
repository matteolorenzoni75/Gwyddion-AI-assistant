"""One installed entrypoint: provision Python packages, verify, then launch."""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ('numpy', 'scipy', 'matplotlib', 'gwyfile', 'PIL', 'igor2',
           'PySide6', 'pyqtgraph', 'pytest', 'mcp', 'sklearn')


def run(args, *, env=None):
    subprocess.run([str(sys.executable), *args], cwd=ROOT, env=env, check=True)


def probe() -> bool:
    code = '; '.join('import ' + name for name in MODULES)
    return subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def provision() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required')
    if sys.prefix == sys.base_prefix:
        raise RuntimeError('Use the AFM Copilot virtual environment, not system Python')
    marker = Path(sys.prefix) / '.afm-dependencies.sha256'
    fingerprint = hashlib.sha256((ROOT / 'pyproject.toml').read_bytes()).hexdigest()
    if not marker.is_file() or marker.read_text().strip() != fingerprint or not probe():
        run(['-m', 'pip', '--disable-pip-version-check', 'install', '-e', '.[gui,dev,ml,mcp]'])
        if not probe():
            raise RuntimeError('Dependency import check failed after installation')
        run(['-m', 'pip', 'check'])
        marker.write_text(fingerprint, encoding='ascii')


def native_smoke() -> None:
    """Real Gwyddion processing on a temporary synthetic scan, never user data."""
    from dataclasses import replace
    import numpy as np
    from afm_copilot.bridge import GwyBridge
    from afm_copilot.gwy_io import Channel, save_height, load_height
    from afm_copilot.ops.recipes import get_recipe
    bridge = GwyBridge()
    report = bridge.self_test()
    print('PyGwy self-test:', report.get('gwy_version', report), flush=True)
    y, x = np.indices((64, 64))
    z = (x * 2 + y * 3) * 1e-10
    raw = Channel('Height', z, 5e-6, 5e-6)
    with tempfile.TemporaryDirectory(prefix='afm-native-smoke-') as directory:
        base = Path(directory)
        source = base / 'synthetic.gwy'
        save_height(raw, source)
        before = source.read_bytes()
        recipe = replace(get_recipe('quick-clean'), key='install-plane-smoke', steps=('plane_level',))
        result = bridge.run_recipe(recipe, [source], base / 'output')
        rows = result.get('results', [])
        if len(rows) != 1 or not rows[0].get('ok') or not rows[0]['steps'][0].get('applied'):
            raise RuntimeError('Native Gwyddion plane-level operation failed')
        output = load_height(rows[0]['output'])
        if (output.data.shape != raw.data.shape or not np.isfinite(output.data).all()
                or not np.isclose(output.xreal, raw.xreal, rtol=1e-8, atol=0)
                or not np.isclose(output.yreal, raw.yreal, rtol=1e-8, atol=0)
                or output.rms > raw.rms * 0.01 or source.read_bytes() != before):
            raise RuntimeError('Native correction failed geometry, RMS or source-integrity check')
    print('Native plane correction: PASS', flush=True)


def test_environment(root: Path) -> dict:
    """Keep tests isolated from the operator's private manifests and raw scans."""
    env = dict(os.environ)
    env.update(USERPROFILE=str(root), HOME=str(root),
               AFM_COPILOT_HOME=str(root / 'installation'), QT_QPA_PLATFORM='offscreen')
    for key in ('AFM_TRAINING_ROOT', 'AFM_TEST_CORPUS_ROOT'):
        env.pop(key, None)
    return env


def verify() -> int:
    from afm_copilot.paths import PRIVATE_ROOT
    logs = PRIVATE_ROOT / 'diagnostics'
    logs.mkdir(parents=True, exist_ok=True)
    logfile = logs / ('verification-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.txt')
    statuses = []
    with tempfile.TemporaryDirectory(prefix='afm-verify-') as directory:
        env = test_environment(Path(directory))
        commands = [
            ('Python dependency consistency', ['-m', 'pip', 'check']),
            ('Repository regression suite', ['-m', 'pytest', '-q', '-ra']),
            ('Native PyGwy smoke test', ['-m', 'afm_copilot.bootstrap', '--native-smoke']),
        ]
        with logfile.open('w', encoding='utf-8') as stream:
            for title, args in commands:
                print('\n=== ' + title + ' ===', flush=True)
                stream.write('\n=== ' + title + ' ===\n')
                stream.flush()
                proc = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace')
                for line in proc.stdout:
                    print(line, end='', flush=True)
                    stream.write(line)
                code = proc.wait()
                statuses.append(code)
                stream.write(f'EXIT CODE: {code}\n')
                stream.flush()
    print('Verification report:', logfile, flush=True)
    return int(any(statuses))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--install-only', action='store_true')
    parser.add_argument('--native-smoke', action='store_true')
    args = parser.parse_args(argv)
    if args.native_smoke:
        native_smoke()
        return 0
    provision()
    if args.verify:
        return verify()
    if args.install_only:
        return 0
    from afm_copilot.launcher import main as launch
    return launch([])


if __name__ == '__main__':
    raise SystemExit(main())
