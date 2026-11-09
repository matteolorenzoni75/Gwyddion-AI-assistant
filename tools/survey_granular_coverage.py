"""Survey spatial texture coverage without assigning semantic labels.

This is a tuning aid, not a production classifier.  It deliberately prints
the quantities for the entire blind export corpus before any threshold is
chosen.  An optional final path is reported as ``probe`` so its source name
cannot become input evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.stats import skew

from afm_copilot.features import subtract_background
from afm_copilot.gwy_io import load_height


def texture_coverage(data: np.ndarray, cells: int = 8) -> dict[str, float]:
    """Describe whether local relief is sparse or fills the whole frame."""
    values = np.asarray(data, dtype=float)
    flat = subtract_background(values, 1)
    finite = np.isfinite(flat)
    if not finite.any():
        return {"coverage": 0.0, "uniformity": 0.0,
                "peak_density": 0.0, "relief_fraction": 0.0}
    fill = float(np.nanmedian(flat))
    flat = np.where(finite, flat, fill)

    spreads: list[float] = []
    for rows in np.array_split(np.arange(flat.shape[0]), cells):
        for cols in np.array_split(np.arange(flat.shape[1]), cells):
            tile = flat[np.ix_(rows, cols)]
            lo, hi = np.percentile(tile, (10.0, 90.0))
            spreads.append(float(hi - lo))
    local = np.asarray(spreads, dtype=float)
    reference = float(np.percentile(local, 90.0))
    coverage = float(np.mean(local >= 0.25 * reference)) if reference > 0 else 0.0
    q20, q80 = np.percentile(local, (20.0, 80.0))
    uniformity = float(q20 / q80) if q80 > 0 else 0.0

    smooth = ndimage.gaussian_filter(flat, 1.0)
    local_baseline = ndimage.gaussian_filter(smooth, 3.0)
    relief = smooth - local_baseline
    median = float(np.median(relief))
    mad = float(np.median(np.abs(relief - median)))
    maxima = smooth == ndimage.maximum_filter(smooth, size=5, mode="nearest")
    strong = relief > median + 2.5 * max(mad, np.finfo(float).eps)
    peak_density = float(np.count_nonzero(maxima & strong) / flat.size)

    global_lo, global_hi = np.percentile(flat, (1.0, 99.0))
    global_relief = float(global_hi - global_lo)
    relief_fraction = reference / global_relief if global_relief > 0 else 0.0
    result = {
        "coverage": coverage,
        "uniformity": uniformity,
        "peak_density": peak_density,
        "relief_fraction": relief_fraction,
    }
    # Local polarity is different from global height polarity.  Close-packed
    # domes can sit on a large scanner slope and therefore look globally
    # "sunken", while their local high-pass shape still points upward.  Pits
    # remain locally negative.  Survey several scales before choosing one.
    for sigma in (4.0, 8.0, 16.0, 32.0):
        highpass = flat - ndimage.gaussian_filter(flat, sigma)
        lo, hi = np.percentile(highpass, (0.5, 99.5))
        clipped = np.clip(highpass, lo, hi)
        result[f"skew_{int(sigma)}"] = float(skew(clipped.ravel()))
        result[f"positive_{int(sigma)}"] = float(np.mean(highpass > 0.0))
        window = max(3, int(round(sigma)))
        spread = float(np.std(clipped))
        high = float(np.median(clipped) + 0.5 * spread)
        low = float(np.median(clipped) - 0.5 * spread)
        maxima = clipped == ndimage.maximum_filter(
            clipped, size=window, mode="nearest")
        minima = clipped == ndimage.minimum_filter(
            clipped, size=window, mode="nearest")
        result[f"maxima_{int(sigma)}"] = float(
            np.count_nonzero(maxima & (clipped > high)) / clipped.size)
        result[f"minima_{int(sigma)}"] = float(
            np.count_nonzero(minima & (clipped < low)) / clipped.size)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, default=Path("export"))
    parser.add_argument("--probe", type=Path)
    args = parser.parse_args()

    baseline = json.loads((args.export / "baseline.json").read_text(
        encoding="utf-8"))
    entries = {entry["name"]: entry for entry in baseline["scans"]}
    rows = []
    for path in sorted((args.export / "scans").glob("scan-*.gwy")):
        try:
            channel = load_height(path)
        except (OSError, ValueError):
            continue
        entry = entries.get(path.stem, {})
        rows.append((path.stem, entry.get("in_the_corpus_because", ""),
                     entry.get("family", ""), entry.get("measurements", {}),
                     texture_coverage(channel.data)))
    if args.probe:
        from afm_copilot.decide import plan_for
        from afm_copilot.features import measure

        channel = load_height(args.probe)
        plan = plan_for(channel)
        rows.append(("probe", "external probe", "unknown",
                     measure(channel, plan.levelling).as_dict(),
                     texture_coverage(channel.data)))

    print("id\tcoverage\tuniformity\tpeaks_per_10k\trelief_fraction\t"
          "skew4\tskew8\tskew16\tskew32\tpos8\tpos16\t"
          "max16\tmin16\tobjects\tpolarity\tcount\t"
          "corr_px\ttilt\tfamily\treason")
    for name, reason, family, measured, metrics in sorted(
            rows, key=lambda row: row[4]["coverage"], reverse=True):
        pixel = float(measured.get("pixel_size", 0.0) or 0.0)
        corr = float(measured.get("correlation_length", 0.0) or 0.0)
        corr_px = corr / pixel if pixel > 0 else 0.0
        print(f"{name}\t{metrics['coverage']:.3f}\t"
              f"{metrics['uniformity']:.3f}\t"
              f"{metrics['peak_density'] * 10000:.2f}\t"
              f"{metrics['relief_fraction']:.3f}\t"
              f"{metrics['skew_4']:.2f}\t{metrics['skew_8']:.2f}\t"
              f"{metrics['skew_16']:.2f}\t{metrics['skew_32']:.2f}\t"
              f"{metrics['positive_8']:.2f}\t{metrics['positive_16']:.2f}\t"
              f"{metrics['maxima_16'] * 10000:.2f}\t"
              f"{metrics['minima_16'] * 10000:.2f}\t"
              f"{float(measured.get('object_fraction', 0.0) or 0.0):.3f}\t"
              f"{int(measured.get('object_polarity', 0) or 0):d}\t"
              f"{int(measured.get('object_count', 0) or 0):d}\t"
              f"{corr_px:.1f}\t"
              f"{float(measured.get('tilt', 0.0) or 0.0):.3f}\t"
              f"{family}\t{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
