"""
What the instrument recorded about the scan, beside the pixels.

Asylum files carry a note with several hundred fields -- the scan speed, the
angle, the feedback gains, the mode, the date, and whether the scanner was
running closed loop. Conversion to Gwyddion drops all of it, and the obvious
fix was to make the bridge carry it through. The simpler fix is this: read the
note in Python 3 straight from the original file, and leave the Python 2.7 side
alone. One small dependency instead of changes on both sides of a bridge.

Only a handful of the fields are used. The rest is kept as it was written, so
nothing has to be added here when a new question comes up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Mains frequency. Where the tip moves at a known speed, a disturbance at a
# fixed frequency writes a fixed spacing into the image -- which is what turns
# "is this a pattern or is it noise" from a judgement into a comparison.
MAINS_HZ = 50.0

_INTERESTING = {
    "ScanRate": "scan_rate",              # lines per second
    "ScanSpeed": "scan_speed",            # metres per second along the fast axis
    "ScanAngle": "scan_angle",            # degrees
    "ScanPoints": "points",
    "ScanLines": "lines",
    "FastScanSize": "fast_size",          # metres
    "SlowScanSize": "slow_size",          # metres
    "IntegralGain": "integral_gain",
    "ProportionalGain": "proportional_gain",
    "DriveFrequency": "drive_frequency",
    "ScanMode": "scan_mode",              # "Closed Loop" / "Open Loop"
    "ImagingMode": "imaging_mode",
    "Date": "date",
    "Time": "time",
}

# The instrument appends this when a setting was changed part-way down the
# frame: "0.40064@Line: 229". It is the only record that the operator or the
# software intervened mid-scan, and it explains images whose character changes
# half way down.
_CHANGED_AT = re.compile(r"@Line:\s*(\d+)")


@dataclass
class Acquisition:
    """The scan settings, as the instrument wrote them."""

    source: str = ""
    scan_rate: float | None = None
    scan_speed: float | None = None
    scan_angle: float | None = None
    points: int | None = None
    lines: int | None = None
    fast_size: float | None = None
    slow_size: float | None = None
    integral_gain: float | None = None
    proportional_gain: float | None = None
    drive_frequency: float | None = None
    scan_mode: str = ""
    imaging_mode: str = ""
    date: str = ""
    time: str = ""
    changed_at_line: int | None = None
    channels: list[str] = field(default_factory=list)
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return bool(self.raw)

    @property
    def closed_loop(self) -> bool | None:
        """Was the scanner's position measured rather than assumed?"""
        if not self.scan_mode:
            return None
        return "closed" in self.scan_mode.lower()

    @property
    def session(self) -> str:
        """A key for grouping scans taken together, hence sharing a state."""
        return self.date or "unknown"

    def noise_spacings(self, harmonics: int = 3,
                       frequency: float = MAINS_HZ) -> list[float]:
        """
        The spacings, in metres, that electrical interference would leave.

        spacing = scan speed / frequency. On a real file: 3.744 um/s over 50 Hz
        is 74.9 nm, with harmonics at 37.4 and 25.0 nm.

        Two cautions before using this to reject anything. It applies **along
        the fast axis only** -- that is the axis time maps onto, and `scan_angle`
        says where it points. And a spacing can coincide with a real structure:
        at that same speed 74.9 nm is also the certified pore pitch of the
        anodic porous alumina in the sample library. Period and direction
        together, never period alone.
        """
        if not self.scan_speed or frequency <= 0:
            return []
        return [self.scan_speed / (frequency * n)
                for n in range(1, max(1, harmonics) + 1)]


def _number(text: str) -> float | None:
    match = re.match(r"\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)", text)
    return float(match.group(1)) if match else None


def read(path: str | Path) -> Acquisition:
    """
    The scan settings from an original instrument file.

    Returns an empty Acquisition rather than raising when the format is not
    one we can read, or the file is damaged: missing metadata must never stop
    a batch, it only means some checks cannot be made.
    """
    path = Path(path)
    acquisition = Acquisition(source=str(path))
    if path.suffix.lower() != ".ibw":
        return acquisition

    try:
        from igor2 import binarywave
        wave = binarywave.load(str(path))["wave"]
    except Exception:                                          # noqa: BLE001
        return acquisition

    note = wave.get("note", b"")
    if isinstance(note, bytes):
        note = note.decode("latin-1", "replace")

    fields: dict[str, str] = {}
    for line in note.replace("\r", "\n").split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    acquisition.raw = fields

    for written, ours in _INTERESTING.items():
        if written not in fields:
            continue
        text = fields[written]
        changed = _CHANGED_AT.search(text)
        if changed:
            acquisition.changed_at_line = int(changed.group(1))
        if ours in ("scan_mode", "imaging_mode", "date", "time"):
            setattr(acquisition, ours, text)
        elif ours in ("points", "lines"):
            value = _number(text)
            setattr(acquisition, ours, int(value) if value is not None else None)
        else:
            setattr(acquisition, ours, _number(text))

    labels = wave.get("labels") or []
    acquisition.channels = [b.decode("latin-1", "replace")
                            for group in labels for b in group if b]
    return acquisition


def find_original(stem: str, folders: list[Path]) -> Path | None:
    """
    The instrument file a converted scan came from.

    Conversion keeps the stem and changes the suffix, so the original can be
    found again without recording a path anywhere -- which keeps this readable
    for scans converted before any of it existed.
    """
    for folder in folders:
        if not folder.is_dir():
            continue
        for suffix in (".ibw", ".IBW"):
            candidate = folder / (stem + suffix)
            if candidate.exists():
                return candidate
    return None
