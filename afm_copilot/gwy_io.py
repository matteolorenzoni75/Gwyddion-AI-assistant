"""
Reading .gwy files in Python 3, without Gwyddion.

`gwyfile` parses the native format directly, so once a raw instrument file has
been converted once (see bridge.convert_raw), every later read is fast, in
process, and free of the Python 2.7 dependency.

Heights come back in SI units -- metres for a topography channel -- because
that is what Gwyddion stores. Presentation code converts to nm or um; nothing
here does, so that no unit conversion happens twice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import gwyfile
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "gwyfile is required to read .gwy files. Install it with:\n"
        "    .venv\\Scripts\\python.exe -m pip install gwyfile") from exc


# Channel titles that carry surface height, as opposed to amplitude, phase,
# deflection, current or potential. Matching is deliberately loose because
# vendors disagree: Asylum writes "HeightRetrace", others "Topography".
_HEIGHT_RE = re.compile(r"height|topograph|z ?sensor|\bzs\b", re.IGNORECASE)
_NON_HEIGHT_RE = re.compile(
    r"amplitude|phase|deflection|friction|lateral|current|potential|"
    r"dissipation|frequency|young|indentation|adhesion|stiffness",
    re.IGNORECASE)


# eq=False keeps identity semantics: a dataclass holding a numpy array cannot
# have field-wise equality, because `chan_a == chan_b` would evaluate an array
# comparison and raise on any truth test, including `x in list_of_channels`.
@dataclass(eq=False)
class Channel:
    """One 2D data channel with its physical scale."""

    name: str
    data: np.ndarray            # shape (yres, xres), SI units
    xreal: float                # metres
    yreal: float                # metres
    xy_unit: str = "m"
    z_unit: str = "m"
    source: Path | None = None
    meta: dict = field(default_factory=dict)

    @property
    def xres(self) -> int:
        return int(self.data.shape[1])

    @property
    def yres(self) -> int:
        return int(self.data.shape[0])

    @property
    def z_range(self) -> float:
        return float(np.nanmax(self.data) - np.nanmin(self.data))

    @property
    def rms(self) -> float:
        """Standard deviation of heights. Note this is the RAW value -- see
        docs/research/QUALITY_METRICS.md on levelling bias before quoting it."""
        return float(np.nanstd(self.data))

    @property
    def pixel_size(self) -> float:
        """Metres per pixel along x."""
        return self.xreal / self.xres if self.xres else float("nan")

    @property
    def is_height(self) -> bool:
        if _NON_HEIGHT_RE.search(self.name):
            return False
        return bool(_HEIGHT_RE.search(self.name)) or self.z_unit == "m"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"Channel({self.name!r}, {self.yres}x{self.xres}, "
                f"{self.xreal:.3g} {self.xy_unit}, z_range={self.z_range:.3g})")


def _unit_string(datafield, key: str, default: str) -> str:
    """Pull a unit out of a gwyfile datafield, tolerating its absence."""
    try:
        unit = datafield[key]
    except (KeyError, TypeError):
        return default
    for attr in ("unitstr", "name"):
        try:
            value = unit[attr]
        except (KeyError, TypeError):
            continue
        if value:
            return str(value)
    return default


def _load_sidecar(path: Path) -> dict:
    """Acquisition metadata written next to the .gwy by convert_raw.py."""
    sidecar = path.with_suffix(".meta.json")
    if not sidecar.is_file():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_channels(path: str | Path) -> list[Channel]:
    """Read every 2D channel from a .gwy file."""
    path = Path(path)
    obj = gwyfile.load(str(path))
    fields = gwyfile.util.get_datafields(obj)
    sidecar = _load_sidecar(path)

    meta_by_title = {}
    for entry in sidecar.get("channels", []):
        meta_by_title[entry.get("title", "")] = entry.get("meta", {})

    channels: list[Channel] = []
    for name, datafield in fields.items():
        data = np.asarray(datafield.data, dtype=float)
        channels.append(Channel(
            name=name,
            data=data,
            xreal=float(datafield["xreal"]),
            yreal=float(datafield["yreal"]),
            xy_unit=_unit_string(datafield, "si_unit_xy", "m"),
            z_unit=_unit_string(datafield, "si_unit_z", "m"),
            source=path,
            meta=meta_by_title.get(name, {}),
        ))
    return channels


def load_height(path: str | Path) -> Channel:
    """
    Read the one channel most likely to be surface topography.

    Prefers an explicitly height-named channel; falls back to the first channel
    measured in metres. Raises if neither exists, rather than silently
    rendering a phase or amplitude map as if it were a surface.
    """
    channels = load_channels(path)
    if not channels:
        raise ValueError(f"{path} contains no 2D channels")

    named = [c for c in channels if _HEIGHT_RE.search(c.name)
             and not _NON_HEIGHT_RE.search(c.name)]
    if named:
        # ZSensor is a truer height than the feedback Height signal, but only
        # when the file offers both; on its own, either is fine.
        preferred = [c for c in named if "sensor" not in c.name.lower()]
        return (preferred or named)[0]

    metric = [c for c in channels if c.z_unit == "m"
              and not _NON_HEIGHT_RE.search(c.name)]
    if metric:
        return metric[0]

    raise ValueError(
        f"{path} has no height-like channel. Found: "
        + ", ".join(f"{c.name} [{c.z_unit}]" for c in channels))


def find_gwy_files(folder: str | Path) -> list[Path]:
    """Every .gwy in a folder, sorted by name for reproducible batches."""
    return sorted(Path(folder).glob("*.gwy"))
