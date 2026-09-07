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
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from afm_copilot import frame, instrument, quality, tip
from afm_copilot.decide import plan_for
from afm_copilot.features import measure
from afm_copilot.gwy_io import Channel, load_height, save_height

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
    # The probe, and whether the image had anything to say about it. Every
    # lateral size in `measurements` is an apparent one until this is applied.
    tip_radius_nm: float | None = None
    tip_source: str = ""
    object_true_radius_nm: float | None = None
    picture: str = ""
    picture_full: str = ""
    contrast: str = ""
    clipped: float = 0.0
    needs_despike: bool = False
    despiked: bool = False
    spike_fraction: float = 0.0
    cleaned: bool = False
    rms_before_nm: float | None = None
    rms_after_nm: float | None = None
    over_flattened: bool = False
    steps: list[str] = field(default_factory=list)
    measurements: dict = field(default_factory=dict)


def _is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_SUFFIXES


def _tally(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


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


def convert(raw: list[Path], into: Path,
            chunk: int = 40) -> tuple[list[Path], list[tuple[Path, str]]]:
    """
    Raw instrument files through Gwyddion, in chunks.

    In chunks because a single failure in one file should not cost the whole
    batch, and because a list of a thousand paths is not something to hand a
    subprocess in one go.

    Returns what converted **and what did not, with the reason**. An earlier
    version returned only the successes, and on a folder that had quietly grown
    to 191 files it read 166 of them without anybody noticing the other 25 had
    gone missing. A batch that promises to be vouched for cannot lose files in
    silence: a file that failed to convert has to be as visible as one that was
    judged and set aside.
    """
    from afm_copilot.bridge import BridgeError, GwyBridge

    into.mkdir(parents=True, exist_ok=True)
    done: list[Path] = []
    failed: list[tuple[Path, str]] = []

    todo = [p for p in raw if not (into / (p.stem + ".gwy")).exists()]
    done.extend(into / (p.stem + ".gwy")
                for p in raw if (into / (p.stem + ".gwy")).exists())

    if todo:
        try:
            bridge = GwyBridge()
        except BridgeError as exc:
            return sorted(set(done)), [(p, f"Gwyddion unreachable: {exc}")
                                       for p in todo]

        for start in range(0, len(todo), chunk):
            _convert_group(bridge, todo[start:start + chunk], into,
                           done, failed)
    return sorted(set(done)), failed


def _convert_group(bridge, group: list[Path], into: Path,
                   done: list[Path], failed: list[tuple[Path, str]]) -> None:
    """
    Convert a group, splitting it in half if the subprocess dies.

    Some files crash Gwyddion outright rather than returning an error -- an
    access violation inside a format reader -- and that kills the subprocess
    with every file it was given. A batch of forty then loses forty, including
    files that had converted perfectly well the day before.

    So a crash is not a verdict on the group. Halve it and try again: the bad
    file is isolated in a handful of passes, and everything around it survives.
    """
    from afm_copilot.bridge import BridgeError

    if not group:
        return
    try:
        report = bridge.convert_raw(group, into)
    except BridgeError as exc:
        if len(group) == 1:
            failed.append((group[0], f"conversion failed: {exc}"[:140]))
            return
        middle = len(group) // 2
        _convert_group(bridge, group[:middle], into, done, failed)
        _convert_group(bridge, group[middle:], into, done, failed)
        return

    # The converter identifies each file by "source" and "stem"; there is no
    # "input" key. Reading the wrong one silently produced two entries for the
    # same failed file.
    accounted = set()
    for record in report.get("results", []):
        stem = record.get("stem") or Path(record.get("source", "")).stem
        accounted.add(stem)
        if record.get("ok"):
            done.append(Path(record["gwy"]))
        else:
            failed.append((Path(record.get("source", stem)),
                           str(record.get("error") or "unknown")[:140]))
    # Anything the report never mentioned is missing too.
    for path in group:
        if path.stem not in accounted:
            failed.append((path, "Gwyddion returned no result for it"))


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


def clean(work: list[tuple[ScanResult, Path]], out: Path,
          despike: bool = False) -> None:
    """
    Run each scan's chosen recipe, and record what it changed.

    `despike` is off by default and has to be asked for. Repairing isolated
    pixels is not free -- on one real scan it cut RMS by 22% -- and no
    measurement here separates a dropout from a small tall feature that is
    genuinely there. See `quality.SPIKES_WORTH_REPAIRING`.

    Grouped by recipe rather than looped per file: one Gwyddion subprocess for
    every recipe in use, not one for every scan. On a batch of a hundred that
    is the difference between seconds and minutes.

    The recipe is never chosen by eye. It comes from `plan_for`, which measures
    -- a recipe picked by looking at a picture once cost 35% of a scan's
    roughness and made a flat object concave, and the number agreed with the
    mistake all the way.
    """
    from afm_copilot.bridge import BridgeError, GwyBridge
    from afm_copilot.ops.recipes import get_recipe

    bridge = GwyBridge()

    # Spikes first, and on their own pass. A single bad pixel drags a
    # background fit towards itself, survives every levelling step, and then
    # stretches the colour range of the finished picture over a height nothing
    # else in the image reaches -- so repairing it after the fact repairs
    # nothing that already went wrong.
    needing = [(entry, path) for entry, path in work
               if entry.needs_despike and despike] if despike else []
    repaired: dict[str, Path] = {}
    if needing:
        try:
            report = bridge.run_recipe(get_recipe("despike"),
                                       [p for _, p in needing],
                                       out / "repaired")
            for record in report.get("results", []):
                # `run_recipe` names the result "output"; `convert_raw` names
                # it "gwy". Reading the wrong one here silently discarded every
                # repair -- the pass ran on 125 scans and reported 0 done.
                if record.get("ok") and record.get("output"):
                    repaired[record["stem"]] = Path(record["output"])
        except (BridgeError, KeyError):
            repaired = {}
        for entry, path in needing:
            if path.stem in repaired:
                entry.despiked = True

    by_recipe: dict[str, list[tuple[ScanResult, Path]]] = {}
    for entry, path in work:
        source = repaired.get(path.stem, path)
        by_recipe.setdefault(entry.recipe or "level-only",
                             []).append((entry, source))
    for key, group in by_recipe.items():
        try:
            recipe = get_recipe(key)
        except KeyError:
            continue
        try:
            report = bridge.run_recipe(recipe, [p for _, p in group],
                                       out / "clean")
        except BridgeError:
            continue

        outcome = {r["stem"]: r for r in report.get("results", [])}
        for entry, path in group:
            record = outcome.get(path.stem)
            if not record or not record.get("ok"):
                continue
            entry.cleaned = True
            entry.rms_before_nm = round(record["initial"]["rms"] * 1e9, 3)
            entry.rms_after_nm = round(record["final"]["rms"] * 1e9, 3)
            entry.steps = [
                s["title"] for s in record.get("steps", []) if s.get("applied")
            ]
            entry.over_flattened = lost_too_much(entry)


def lost_too_much(entry: ScanResult) -> bool:
    """
    Did the cleaning take more roughness than the background can account for?

    Removing a background legitimately costs roughness, and the amount is
    predictable: if a fitted background explains a fraction f of the height
    variance, what should survive is sqrt(1 - f) of the RMS. A scan that ends
    up far below that has lost surface, not artifact.

    Two ways it happens, both seen on the real batch. Row alignment on a nearly
    flat surface covered in small features subtracts the features along with
    the line offsets -- the median of a row's differences cannot tell them
    apart. And masking "objects" on a lithographic pattern masks the pattern,
    so levelling flattens the thing being measured.

    Flagged, not corrected. Which recipe is right is a judgement about what the
    sample is, and choosing one by rule of thumb is how a scan was ruined
    before, with the numbers agreeing all the way.
    """
    if not entry.rms_before_nm or not entry.rms_after_nm:
        return False
    explained = (entry.measurements or {}).get("explained_by_degree") or {}
    order = (entry.measurements or {}).get("background_order", 1)
    fraction = explained.get(order, explained.get(str(order), 0.0)) or 0.0
    expected = math.sqrt(max(0.0, 1.0 - min(float(fraction), 0.999999)))
    kept = entry.rms_after_nm / entry.rms_before_nm
    # Generous: the recipes also despike and align rows, which cost something
    # on any real surface. Only a scan far below the prediction is flagged.
    return kept < 0.4 * expected and (1.0 - kept) > 0.5


def draw(work: list[tuple[ScanResult, Path]], out: Path) -> None:
    """
    Write the picture of each scan, with the contrast put where the subject is.

    This is the thing that leaves the lab. It is drawn per scan rather than on
    one shared scale, because the job here is that each image be legible; a set
    meant to be *compared* needs one range across all of it, which is what
    `afm-copilot batch-images --auto-group` is for. Which of the two you want
    depends on the question, so the report says which was done.
    """
    from afm_copilot.render import (ColorScale, RenderStyle,
                                    guided_color_scale, pick_unit,
                                    render_channel)

    style = RenderStyle()
    gwyddion_ranges = _gwyddion_ranges([p for _, p in work])

    for entry, path in work:
        try:
            channel = load_height(path)
        except Exception:                                      # noqa: BLE001
            continue

        try:
            scale, note = guided_color_scale(channel)
            render_channel(channel, out / "images" / f"{entry.name}.png",
                           scale, style=style, title=entry.name)
            entry.picture = f"images/{entry.name}.png"
            entry.contrast = note.get("reason", "")
            entry.clipped = round(float(note.get("clipped", 0.0)), 4)
        except Exception:                                      # noqa: BLE001
            pass

        # And the same scan as Gwyddion would show it, so there is always the
        # familiar picture to compare against. Not a fallback: the two answer
        # different questions, and seeing them side by side is what makes the
        # narrowing on the guided one legible as a choice rather than a quirk.
        band = gwyddion_ranges.get(path.stem)
        if band is None:
            continue
        try:
            data = np.asarray(channel.data, dtype=float)
            finite = data[np.isfinite(data)]
            base = float(finite.min()) if finite.size else 0.0
            vmin, vmax = band[0] - base, band[1] - base
            if vmax <= vmin:
                continue
            factor, unit = pick_unit(vmax - vmin)
            render_channel(
                channel, out / "images" / "full" / f"{entry.name}.png",
                ColorScale(vmin=vmin, vmax=vmax, unit_factor=factor,
                           unit_name=unit),
                style=style, title=entry.name)
            entry.picture_full = f"images/full/{entry.name}.png"
        except Exception:                                      # noqa: BLE001
            continue


def _gwyddion_ranges(paths: list[Path]) -> dict[str, list[float]]:
    """
    Gwyddion's own automatic colour range for each file, in one call.

    Asked for rather than imitated: the method is documented as unspecified, so
    an approximation would look almost right and be quietly different from what
    the user sees when they open the same file themselves.

    An empty result is not a failure worth stopping for -- it costs the second
    picture, nothing else.
    """
    if not paths:
        return {}
    try:
        from afm_copilot.bridge import GwyBridge
        report = GwyBridge().run_script(
            "autorange.py", [str(p) for p in paths], timeout=900.0)
    except Exception:                                          # noqa: BLE001
        return {}
    return report.get("ranges", {}) or {}


def run(inputs: list[Path], out: Path, *, deduplicate: bool = True,
        do_clean: bool = True, do_draw: bool = True,
        do_despike: bool = False) -> dict:
    """
    Take a batch through every stage and report what happened.

    Nothing is deleted. A scan judged unusable is recorded with the reason and
    left out of the measurements -- the decision is visible and reversible,
    which is the difference between a tool that filters and one that silently
    loses data.
    """
    out.mkdir(parents=True, exist_ok=True)
    gwy, raw = collect(inputs)
    unconverted: list[tuple[Path, str]] = []
    if raw:
        converted, unconverted = convert(raw, out / "_gwy")
        gwy.extend(converted)
    gwy = sorted(set(gwy))

    # Where to look for the instrument's original file, which still holds the
    # scan note after conversion has dropped it.
    originals = [p if p.is_dir() else p.parent for p in inputs]

    results: list[ScanResult] = [
        ScanResult(name=path.stem, source=str(path), kept=False,
                   verdict="unreadable", why=[reason])
        for path, reason in unconverted
    ]
    seen: list[tuple[str, np.ndarray]] = []
    # What to hand Gwyddion for cleaning: the cropped copy where the frame had
    # to be trimmed, the original file otherwise.
    to_clean: list[tuple[ScanResult, Path]] = []

    for path in gwy:
        name = path.stem
        try:
            channel = load_height(path)
        except Exception as exc:                               # noqa: BLE001
            # Deliberately everything. A damaged file can fail in whatever way
            # its parser happens to fail -- a truncated .gwy raises an
            # AssertionError from deep inside the reader -- and one bad file in
            # a folder of a thousand must cost that file, not the batch.
            #
            # But a file with no height channel is not damaged. Eight phase
            # maps in one batch were filed under "could not read", which reads
            # as an accusation against perfectly good files: they are simply
            # not topography, and this is a height-only pipeline for now.
            message = str(exc)
            if "no height-like channel" in message:
                results.append(ScanResult(
                    name=name, source=str(path), kept=False,
                    verdict="not topography",
                    why=["no height channel in it — " +
                         message.split("Found: ")[-1][:90]]))
            else:
                results.append(ScanResult(
                    name=name, source=str(path), kept=False,
                    verdict="unreadable",
                    why=[f"{type(exc).__name__}: {exc}"[:140] or "unreadable"]))
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
        source_for_cleaning = path
        if report["interrupted"]:
            entry.cropped_from = report["rows_total"]
            entry.size_um = round(cropped.xreal * 1e6, 3)
            # Written back out so the recipes work on the trimmed frame. A
            # background fitted through the empty band is fitted to nothing.
            source_for_cleaning = save_height(
                cropped, out / "prepared" / (name + ".gwy"))

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
        entry.needs_despike = plan.needs_despike
        entry.spike_fraction = round(plan.spike_fraction, 5)
        # One levelling for the whole scan. Measuring on its own would fit the
        # background again and report a surface slightly different from the one
        # the plan was decided on.
        entry.measurements = measure(cropped, plan.levelling).as_dict()

        # What the probe did to the widths. The measurement is an apparent
        # size until this is applied, and which radius was used has to travel
        # with the number -- the same particle reads half again as wide through
        # a coated probe as through a bare one.
        probe = tip.for_scan(plan.levelling.flat, cropped.pixel_size)
        entry.tip_radius_nm = round(probe.radius * 1e9, 2)
        entry.tip_source = probe.source
        apparent = entry.measurements.get("object_median_size") or 0.0
        if apparent > 0:
            entry.object_true_radius_nm = round(
                tip.feature_radius(apparent, probe.radius) * 1e9, 2)
        results.append(entry)
        to_clean.append((entry, source_for_cleaning))

    if do_clean and to_clean:
        try:
            clean(to_clean, out, despike=do_despike)
        except Exception:                                      # noqa: BLE001
            # Cleaning needs Gwyddion; measuring and judging do not. Losing the
            # cleaning step should not cost the rest of the report.
            pass

    if do_draw and to_clean:
        # Draw the cleaned scan where cleaning worked, the prepared one where
        # it did not: the picture should show what the numbers describe.
        drawable = [
            (entry, out / "clean" / (source.stem + ".gwy")
             if entry.cleaned and (out / "clean" / (source.stem + ".gwy")).exists()
             else source)
            for entry, source in to_clean
        ]
        draw(drawable, out)

    kept = [r for r in results if r.kept]
    summary = {
        "scans_read": len(results),
        "kept": len(kept),
        "discarded": sum(1 for r in results if r.verdict == "discard"),
        "duplicates": sum(1 for r in results if r.duplicate_of),
        "unreadable": sum(1 for r in results if r.verdict == "unreadable"),
        "not_topography": sum(1 for r in results
                              if r.verdict == "not topography"),
        "good": sum(1 for r in kept if r.verdict == "good"),
        "needed_work": sum(1 for r in kept if r.verdict == "fixable"),
        "cropped": sum(1 for r in kept if r.cropped_from),
        "cleaned": sum(1 for r in kept if r.cleaned),
        "needed_despike": sum(1 for r in kept if r.needs_despike),
        "despiked": sum(1 for r in kept if r.despiked),
        "over_flattened": sum(1 for r in kept if r.over_flattened),
        "tip_from_image": sum(1 for r in kept if r.tip_source == "image"),
        "drawn": sum(1 for r in kept if r.picture),
        "drawn_full": sum(1 for r in kept if r.picture_full),
        "contrast_guided": sum(1 for r in kept
                               if r.picture and "tower over" in r.contrast),
        "recipes_used": _tally(r.recipe for r in kept if r.cleaned),
        "results": [asdict(r) for r in results],
    }
    (out / "batch.json").write_text(json.dumps(summary, indent=1, default=float),
                                    encoding="utf-8")
    return summary
