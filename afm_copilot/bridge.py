"""
The Python 3 -> Python 2.7 bridge.

Gwyddion's PyGwy binding is Python 2.7 only and exists solely in the 32-bit
Windows build. Rather than let that constrain the whole application, it is
confined to this one module: everything else in afm_copilot runs on modern
Python 3 and talks to Gwyddion through short-lived subprocesses that exchange
JSON.

There is no `--script` flag on gwyddion.exe -- it does not exist, in any
spelling. What works, and what this module does, is import Gwyddion's standalone
`gwy.pyd` from a plain Python 2.7 interpreter with the right PATH/PYTHONPATH.
Gwyddion registers all its processing modules on import, so no GUI is involved.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYGWY_DIR = PROJECT_ROOT / "pygwy"

DEFAULT_GWYDDION_ROOT = Path(r"C:\Program Files (x86)\Gwyddion")
DEFAULT_PYTHON27 = Path(r"C:\Python27\python.exe")

# PyGwy emits these on import from the GLib type system. They are noise, not
# errors, and drowning real messages in them helps nobody.
_BENIGN_STDERR = ("Trying to register gtype", "GLib-GObject", "Gtk-WARNING")


class BridgeError(RuntimeError):
    """Raised when the Python 2.7 side could not be run, or failed."""


@dataclass
class BridgeConfig:
    """Where Gwyddion and Python 2.7 live. Both are overridable by env var."""

    gwyddion_root: Path = field(
        default_factory=lambda: Path(
            os.environ.get("GWYDDION_ROOT", DEFAULT_GWYDDION_ROOT)))
    python27: Path = field(
        default_factory=lambda: Path(
            os.environ.get("PYTHON27", DEFAULT_PYTHON27)))

    def validate(self) -> None:
        if not self.gwyddion_root.is_dir():
            raise BridgeError(
                f"Gwyddion not found at {self.gwyddion_root}. "
                f"Set the GWYDDION_ROOT environment variable to its install "
                f"directory. Note PyGwy exists only in the 32-bit build.")
        if not (self.gwyddion_root / "bin" / "gwy.pyd").is_file():
            raise BridgeError(
                f"{self.gwyddion_root} has no bin/gwy.pyd, so it has no Python "
                f"support. This is normal for 64-bit Gwyddion -- install the "
                f"32-bit package, which is the only one with PyGwy.")
        if not self.python27.is_file():
            raise BridgeError(
                f"Python 2.7 not found at {self.python27}. Set the PYTHON27 "
                f"environment variable. It must be the 32-bit build, to match "
                f"Gwyddion.")

    def environment(self) -> dict[str, str]:
        """Process environment with Gwyddion's libraries reachable."""
        env = dict(os.environ)
        gwy_bin = str(self.gwyddion_root / "bin")
        gwy_pygwy = str(self.gwyddion_root / "share" / "gwyddion" / "pygwy")
        env["PATH"] = gwy_bin + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = os.pathsep.join([gwy_bin, gwy_pygwy])
        env["GWYDDION_ROOT"] = str(self.gwyddion_root)
        return env


def _clean_stderr(text: str) -> str:
    keep = [ln for ln in text.splitlines()
            if ln.strip() and not any(b in ln for b in _BENIGN_STDERR)]
    return "\n".join(keep)


class GwyBridge:
    """Runs a PyGwy script and returns whatever JSON it printed."""

    def __init__(self, config: BridgeConfig | None = None):
        self.config = config or BridgeConfig()
        self.config.validate()

    def run_script(
        self,
        script: str | Path,
        args: list[str] | None = None,
        timeout: float = 600.0,
    ) -> dict:
        """
        Execute a script from pygwy/ and parse its stdout as JSON.

        `script` may be a bare filename, in which case it is looked up in the
        project's pygwy/ directory.
        """
        script_path = Path(script)
        if not script_path.is_absolute():
            script_path = PYGWY_DIR / script_path
        if not script_path.is_file():
            raise BridgeError(f"PyGwy script not found: {script_path}")

        cmd = [str(self.config.python27), str(script_path), *(args or [])]
        try:
            proc = subprocess.run(
                cmd,
                env=self.config.environment(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise BridgeError(
                f"{script_path.name} did not finish within {timeout:.0f}s"
            ) from exc

        stderr = _clean_stderr(proc.stderr or "")
        if proc.returncode != 0:
            raise BridgeError(
                f"{script_path.name} exited with code {proc.returncode}"
                + (f":\n{stderr}" if stderr else ""))

        out = (proc.stdout or "").strip()
        if not out:
            raise BridgeError(
                f"{script_path.name} produced no output"
                + (f". stderr:\n{stderr}" if stderr else ""))
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise BridgeError(
                f"{script_path.name} did not print valid JSON: {exc}\n"
                f"First 400 characters were:\n{out[:400]}") from exc

    def convert_raw(
        self,
        paths: list[str | Path],
        out_dir: str | Path,
        timeout: float = 600.0,
    ) -> dict:
        """
        Convert raw instrument files to .gwy plus a metadata sidecar.

        This is how any format Gwyddion can read enters the Python 3 side.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        args = ["--out", str(out_dir), *[str(p) for p in paths]]
        return self.run_script("convert_raw.py", args, timeout=timeout)

    def self_test(self) -> dict:
        """Confirm the Python 2.7 side can import gwy and see its modules."""
        return self.run_script("selftest.py", timeout=120.0)
