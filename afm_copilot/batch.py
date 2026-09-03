"""
The whole path, start to finish, on one scan or on a thousand.

This is the normal way the tool is used, not a convenience wrapper: a folder of
whatever the instrument wrote goes in, and what comes out is a set of scans
that have been checked, cropped, cleaned, measured and laid out -- with the
faulty ones set aside and a reason attached to each.

The stages are separate on purpose. Every one of them can be looked at, argued
with, and rerun without the others, because the point is not that the machine
decides but that a person can see what it decided and why.

    read  ->  check  ->  crop  ->  clean  ->  measure  ->  lay out  ->  report
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from afm_copilot import frame, instrument, quality
from afm_copilot.decide import plan_for
from afm_copilot.features import measure
from afm_copilot.gwy_io import Channel, load_height

RAW_SUFFIXES = {".ibw", ".tiff", ".tif", ".spm", ".nid", ".mi", ".sxm", ".jpk"}


@dataclass
class ScanResult:
    """What happened to one scan, in a form a person can read."""

    name: str
    source: str
    kept: bool
    verdict: str                       # good | fixable | discard | unreadable
    why: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    cropped_from: int | None = None
    size_um: float = 0.0
    pixel_nm: float = 0.0
    recipe: str = ""
    # From the instrument's own note, when the original file is still around.
    # Session dates scans taken together, which is what lets one calibration
    # sample speak for the rest of them.
    session: str = ""
    scan_mode: str = ""
    measurements: dict = field(default_factory=dict)


def _is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_SUFFIXES


def collect(inputs: list[Path]) -> tuple[list[Path], list[Path]]:
    """Split what was handed to us into ready-to-read and needs-converting."""
    gwy, raw = [], []
    for item in inputs:
        paths = sorted(item.rglob("*")) if item.is_dir() else [item]
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix.lower() == ".gwy":
                gwy.append(path)
            elif _is_raw(path):
                raw.append(path)
    return gwy, raw


def convert(raw: list[Path], into: Path, chunk: int = 40) -> list[Path]:
    """
    Raw instrument files through Gwyddion, in chunks.

    In chunks because a single failure in one file should not cost the whole
    batch, and because a list of a thousand paths is not something to hand a
    subprocess in one go.
    """
    from afm_copilot.bridge import BridgeError, GwyBridge

    into.mkdir(parents=True, exist_ok=True)
    done: list[Path] = []
    todo = [p for p in raw if not (into / (p.stem + ".gwy")).exists()]
    done.extend(into / (p.stem + ".gwy")
                for p in raw if (into / (p.stem + ".gwy")).exists())

    if todo:
        bridge = GwyBridge()
        for start in range(0, len(todo), chunk):
            batch = todo[start:start + chunk]
            try:
                report = bridge.convert_raw(batch, into)
            except BridgeError:
                continue
            done.extend(Path(r["gwy"]) for r in report["results"] if r["ok"])
    return sorted(set(done))


def _fingerprint(data: np.ndarray) -> np.ndarray:
    """
    A small, scale-free summary used to spot the same surface twice.

    Trace and retrace are the same area scanned there and back, so their pixels
    differ slightly and an exact fingerprint never matches. Comparing coarse
    versions of the levelled surface does.
    """
    from afm_copilot.features import subtract_background

    flat = subtract_background(np.asarray(data, dtype=float), 1)
    h, w = flat.shape
    step_y, step_x = max(1, h // 32), max(1, w // 32)
    small = flat[::step_y, ::step_x][:32, :32].astype(float)
    small = small - np.nanmean(small)
    spread = np.nanstd(small)
    return (small / spread) if spread > 0 else small


def _looks_the_same(a: np.ndarray, b: np.ndarray, threshold: float = 0.97) -> bool:
    if a.shape != b.shape:
        return False
    both = np.isfinite(a) & np.isfinite(b)
    if both.sum() < 64:
        return False
    return bool(np.corrcoef(a[both].ravel(), b[both].ravel())[0, 1] > threshold)


def run(inputs: list[Path], out: Path, *, deduplicate: bool = True,
        keep_discarded: bool = True) -> dict:
    """
    Take a batch through every stage and report what happened.

    Nothing is deleted. A scan judged unusable is recorded with the reason and
    left out of the measurements -- the decision is visible and reversible,
    which is the difference between a tool that filters and one that silently
    loses data.
    """
    out.mkdir(parents=True, exist_ok=True)
    gwy, raw = collect(inputs)
    if raw:
        gwy.extend(convert(raw, out / "_gwy"))
    gwy = sorted(set(gwy))

    # Where to look for the instrument's original file, which still holds the
    # scan note after conversion has dropped it.
    originals = [p if p.is_dir() else p.parent for p in inputs]

    results: list[ScanResult] = []
    seen: list[tuple[str, np.ndarray]] = []

    for path in gwy:
        name = path.stem
        try:
            channel = load_height(path)
        except (ValueError, OSError) as exc:
            results.append(ScanResult(name=name, source=str(path), kept=False,
                                      verdict="unreadable", why=[str(exc)[:120]]))
            continue

        original = instrument.find_original(name, originals)
        acquisition = instrument.read(original) if original else None
        verdict = quality.assess(channel, acquisition)
        entry = ScanResult(
            name=name, source=str(path),
            kept=verdict.verdict != "discard",
            verdict=verdict.verdict,
            why=[c.says for c in verdict.problems],
            size_um=round(channel.xreal * 1e6, 3),
            pixel_nm=round(channel.pixel_size * 1e9, 2),
            session=acquisition.session if acquisition else "",
            scan_mode=acquisition.scan_mode if acquisition else "",
        )

        if verdict.verdict == "discard":
            results.append(entry)
            continue

        cropped, report = frame.crop_to_data(channel)
        if report["interrupted"]:
            entry.cropped_from = report["rows_total"]
            entry.size_um = round(cropped.xreal * 1e6, 3)

        if deduplicate:
            mark = _fingerprint(cropped.data)
            match = next((n for n, m in seen if _looks_the_same(mark, m)), None)
            if match:
                entry.duplicate_of = match
                entry.kept = False
                results.append(entry)
                continue
            seen.append((name, mark))

        plan = plan_for(cropped)
        entry.recipe = plan.recipe_key
        entry.measurements = measure(cropped).as_dict()
        results.append(entry)

    kept = [r for r in results if r.kept]
    summary = {
        "scans_read": len(results),
        "kept": len(kept),
        "discarded": sum(1 for r in results if r.verdict == "discard"),
        "duplicates": sum(1 for r in results if r.duplicate_of),
        "unreadable": sum(1 for r in results if r.verdict == "unreadable"),
        "good": sum(1 for r in kept if r.verdict == "good"),
        "needed_work": sum(1 for r in kept if r.verdict == "fixable"),
        "cropped": sum(1 for r in kept if r.cropped_from),
        "results": [asdict(r) for r in results],
    }
    (out / "batch.json").write_text(json.dumps(summary, indent=1, default=float),
                                    encoding="utf-8")
    return summary
