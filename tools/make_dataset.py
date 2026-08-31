# -*- coding: utf-8 -*-
"""
make_dataset.py  --  PYTHON 2.7 ONLY (PyGwy + numpy)

Generates an arbitrarily large labelled AFM training set with EXACT ground
truth, to solve the data-scarcity problem: real annotated AFM artifact data
barely exists, and hand-labelling is slow and subjective.

Each sample is built as:

    clean surface  ->  a randomly chosen set of artifacts with known
                       parameters  ->  degraded surface

Both are saved as .gwy with correct physical units, alongside a labels row
recording exactly which artifacts were applied and with what parameters. That
gives supervision for three different jobs at once:

  * classification  -- which artifacts are present (multi-label)
  * regression      -- their parameters (stripe angle, tilt slope, ...)
  * restoration     -- clean/degraded pairs for a learned corrector

The most valuable label is the hardest problem in the literature: telling
GENUINE periodic sample structure from PERIODIC NOISE. Surfaces of kind
"grating" and "lattice" carry real periodicity; the "hum" artifact adds fake
periodicity at an arbitrary angle. A model trained here sees both, correctly
labelled, which is supervision no published AFM dataset provides.

Physical scales are taken from the real files surveyed in
docs/data_survey/CHANNEL_SURVEY.md, so the synthetic data occupies the same
regime as the instrument's own output.

Usage, via tools/run_py27.ps1:
    run_py27.ps1 tools\make_dataset.py --n 200 --size 256 --out data\synthetic

Python 2.7 constraints apply: no f-strings, no pathlib, no type hints.
"""

from __future__ import print_function, division

import csv
import json
import math
import os
import random
import sys

import numpy as np

import gwy
import gwyutils


HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)

# Ranges observed in the real data (docs/data_survey/CHANNEL_SURVEY.md):
# scan sizes 5e-6 .. 5e-5 m, z ranges ~7e-8 .. 1.4e-6 m, 256 and 512 px.
SCAN_SIZES = [5.0e-6, 1.0e-5, 2.0e-5, 5.0e-5]
Z_RANGES = (7.0e-8, 1.4e-6)

SURFACE_KINDS = [
    "rough",       # fractal / spectral-synthesis background
    "grating",     # REAL periodicity -- the negative control for hum
    "lattice",     # REAL 2D periodicity
    "particles",   # isolated bumps on a flat base
    "terraces",    # quantised steps
    "smooth",      # low-order polynomial, polymer-like
]

# Artifact names double as the label column names.
ARTIFACTS = [
    "tilt",
    "bow",
    "row_offsets",
    "scars",
    "spikes",
    "hum",
    "line_noise",
]


# ---------------------------------------------------------------------------
# Clean surfaces
# ---------------------------------------------------------------------------

def _spectral_surface(n, beta, rng=None):
    """
    Isotropic surface with a 1/f^beta power spectrum (spectral synthesis).

    Uses numpy's global RNG, which main() seeds, rather than the `random`
    instance -- the two have incompatible signatures for array-shaped draws.
    The `rng` argument is accepted and ignored so callers can stay uniform.
    """
    kx = np.fft.fftfreq(n).reshape(1, n)
    ky = np.fft.fftfreq(n).reshape(n, 1)
    k = np.sqrt(kx * kx + ky * ky)
    k[0, 0] = 1.0
    amp = k ** (-beta / 2.0)
    amp[0, 0] = 0.0
    phase = np.random.uniform(0.0, 2.0 * np.pi, (n, n))
    spec = amp * np.exp(1j * phase)
    surf = np.real(np.fft.ifft2(spec))
    return surf


def _normalise(a, z_range):
    """Scale an array to span exactly z_range metres, centred on zero."""
    span = a.max() - a.min()
    if span <= 0:
        return np.zeros_like(a)
    return (a - a.min()) / span * z_range - z_range / 2.0


def make_surface(kind, n, z_range, rng):
    """Return a clean height array in metres, plus a dict of its true parameters."""
    truth = {"surface_kind": kind}

    if kind == "rough":
        beta = rng.uniform(2.0, 3.5)
        a = _spectral_surface(n, beta, rng)
        truth["psd_beta"] = round(beta, 3)

    elif kind == "grating":
        # Real 1D periodicity at an arbitrary angle -- deliberately similar to
        # what hum produces, so the discriminator has to work for its living.
        period_px = rng.uniform(8.0, 40.0)
        angle = rng.uniform(0.0, math.pi)
        y, x = np.mgrid[0:n, 0:n].astype(float)
        proj = x * math.cos(angle) + y * math.sin(angle)
        a = np.sign(np.sin(2.0 * np.pi * proj / period_px))
        a = a + 0.15 * _spectral_surface(n, 2.5, rng) / (
            np.abs(_spectral_surface(n, 2.5, rng)).max() + 1e-30)
        truth["true_period_px"] = round(period_px, 2)
        truth["true_angle_deg"] = round(math.degrees(angle), 2)

    elif kind == "lattice":
        # Real 2D periodicity: a full reciprocal lattice, which is exactly the
        # structure the "is it noise?" test looks for.
        p1 = rng.uniform(10.0, 30.0)
        p2 = rng.uniform(10.0, 30.0)
        ang = rng.uniform(0.0, math.pi / 2.0)
        y, x = np.mgrid[0:n, 0:n].astype(float)
        u = x * math.cos(ang) + y * math.sin(ang)
        v = -x * math.sin(ang) + y * math.cos(ang)
        a = np.sin(2 * np.pi * u / p1) * np.sin(2 * np.pi * v / p2)
        truth["true_period_px"] = round(min(p1, p2), 2)
        truth["true_angle_deg"] = round(math.degrees(ang), 2)

    elif kind == "particles":
        a = np.zeros((n, n))
        count = rng.randint(8, 60)
        y, x = np.mgrid[0:n, 0:n].astype(float)
        for _ in range(count):
            cx = rng.uniform(0, n)
            cy = rng.uniform(0, n)
            r = rng.uniform(n / 60.0, n / 14.0)
            h = rng.uniform(0.4, 1.0)
            a += h * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2.0 * r * r)))
        truth["n_particles"] = count

    elif kind == "terraces":
        base = _spectral_surface(n, 3.0, rng)
        levels = rng.randint(2, 6)
        b = (base - base.min()) / (base.max() - base.min() + 1e-30)
        a = np.floor(b * levels) / float(levels)
        truth["n_terraces"] = levels

    else:  # "smooth"
        y, x = np.mgrid[0:n, 0:n].astype(float) / float(n)
        a = (rng.uniform(-1, 1) * x ** 2 + rng.uniform(-1, 1) * y ** 2 +
             rng.uniform(-1, 1) * x * y + rng.uniform(-1, 1) * x +
             rng.uniform(-1, 1) * y)
        a = a + 0.05 * _spectral_surface(n, 3.0, rng) / (
            np.abs(_spectral_surface(n, 3.0, rng)).max() + 1e-30)

    return _normalise(a, z_range), truth


# ---------------------------------------------------------------------------
# Artifacts -- each returns a dict of the parameters it actually applied
# ---------------------------------------------------------------------------

def add_tilt(a, z_range, rng):
    n = a.shape[0]
    y, x = np.mgrid[0:n, 0:n].astype(float) / float(n)
    sx = rng.uniform(-3.0, 3.0) * z_range
    sy = rng.uniform(-3.0, 3.0) * z_range
    a += sx * x + sy * y
    return {"tilt_x_m": sx, "tilt_y_m": sy}


def add_bow(a, z_range, rng):
    n = a.shape[0]
    y, x = np.mgrid[0:n, 0:n].astype(float) / float(n) - 0.5
    amp = rng.uniform(-4.0, 4.0) * z_range
    a += amp * (x * x + y * y)
    return {"bow_amp_m": amp}


def add_row_offsets(a, z_range, rng):
    """Random per-row z offsets -- the classic 'banding' artifact."""
    n = a.shape[0]
    sigma = rng.uniform(0.02, 0.35) * z_range
    offsets = np.random.normal(0.0, sigma, n)
    a += offsets.reshape(n, 1)
    return {"row_offset_sigma_m": sigma}


def add_scars(a, z_range, rng):
    """Short horizontal streaks, 1-3 px tall, positive or negative."""
    n = a.shape[0]
    count = rng.randint(1, 12)
    amp = rng.uniform(0.15, 1.2) * z_range
    for _ in range(count):
        row = rng.randint(0, n - 1)
        width = rng.randint(1, 3)
        length = rng.randint(int(n * 0.05), int(n * 0.5))
        col = rng.randint(0, max(1, n - length))
        sign = 1.0 if rng.random() < 0.5 else -1.0
        a[row:row + width, col:col + length] += sign * amp
    return {"n_scars": count, "scar_amp_m": amp}


def add_spikes(a, z_range, rng):
    n = a.shape[0]
    count = rng.randint(1, 40)
    amp = rng.uniform(1.0, 6.0) * z_range
    for _ in range(count):
        r = rng.randint(0, n - 1)
        c = rng.randint(0, n - 1)
        a[r, c] += amp * (1.0 if rng.random() < 0.5 else -1.0)
    return {"n_spikes": count, "spike_amp_m": amp}


def add_hum(a, z_range, rng):
    """
    FAKE periodicity: a sinusoidal ripple at an ARBITRARY angle.

    This is the artifact that must never be confused with a real grating or
    lattice, so its angle and period are recorded exactly.
    """
    n = a.shape[0]
    period_px = rng.uniform(3.0, 30.0)
    angle = rng.uniform(0.0, math.pi)
    amp = rng.uniform(0.03, 0.5) * z_range
    y, x = np.mgrid[0:n, 0:n].astype(float)
    proj = x * math.cos(angle) + y * math.sin(angle)
    a += amp * np.sin(2.0 * np.pi * proj / period_px + rng.uniform(0, 6.28))
    # Real hum brings harmonics along the same direction.
    if rng.random() < 0.5:
        a += 0.3 * amp * np.sin(4.0 * np.pi * proj / period_px)
    return {"hum_period_px": round(period_px, 3),
            "hum_angle_deg": round(math.degrees(angle), 3),
            "hum_amp_m": amp}


def add_line_noise(a, z_range, rng):
    """High-frequency noise along the fast axis only."""
    n = a.shape[0]
    sigma = rng.uniform(0.01, 0.15) * z_range
    a += np.random.normal(0.0, sigma, (n, n))
    return {"line_noise_sigma_m": sigma}


ARTIFACT_FUNCS = {
    "tilt": add_tilt,
    "bow": add_bow,
    "row_offsets": add_row_offsets,
    "scars": add_scars,
    "spikes": add_spikes,
    "hum": add_hum,
    "line_noise": add_line_noise,
}


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save_gwy(array, path, xreal, title):
    """Write a numpy height array to a .gwy file with proper metres units."""
    n = array.shape[0]
    field = gwy.DataField(n, n, xreal, xreal, True)
    view = gwyutils.data_field_data_as_array(field)
    view[:, :] = array
    field.get_si_unit_xy().set_from_string("m")
    field.get_si_unit_z().set_from_string("m")

    container = gwy.Container()
    container.set_object_by_name("/0/data", field)
    container.set_string_by_name("/0/data/title", title)
    gwy.gwy_file_save(container, path, gwy.RUN_NONINTERACTIVE)


def parse_args(argv):
    opts = {"n": 200, "size": 256, "out": os.path.join(PROJECT_ROOT, "data", "synthetic"),
            "seed": 1234, "save_gwy": True}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--n":
            i += 1; opts["n"] = int(argv[i])
        elif a == "--size":
            i += 1; opts["size"] = int(argv[i])
        elif a == "--out":
            i += 1; opts["out"] = argv[i]
        elif a == "--seed":
            i += 1; opts["seed"] = int(argv[i])
        elif a == "--labels-only":
            opts["save_gwy"] = False
        i += 1
    return opts


def main():
    opts = parse_args(sys.argv[1:])
    rng = random.Random(opts["seed"])
    np.random.seed(opts["seed"])

    out_dir = opts["out"]
    clean_dir = os.path.join(out_dir, "clean")
    dirty_dir = os.path.join(out_dir, "degraded")
    for d in (out_dir, clean_dir, dirty_dir):
        if not os.path.isdir(d):
            os.makedirs(d)

    n = opts["size"]
    rows = []

    print("Generating %d samples at %dx%d px" % (opts["n"], n, n))
    print("Output: %s\n" % out_dir)

    for idx in range(opts["n"]):
        kind = rng.choice(SURFACE_KINDS)
        xreal = rng.choice(SCAN_SIZES)
        z_range = rng.uniform(*Z_RANGES)

        clean, truth = make_surface(kind, n, z_range, rng)
        dirty = clean.copy()

        # Each artifact fires independently, so the label set is genuinely
        # multi-label rather than one-artifact-per-image.
        applied = {}
        for name in ARTIFACTS:
            if rng.random() < 0.45:
                applied[name] = ARTIFACT_FUNCS[name](dirty, z_range, rng)

        stem = "%05d_%s" % (idx, kind)
        row = {
            "id": idx,
            "stem": stem,
            "surface_kind": kind,
            "xres": n,
            "yres": n,
            "xreal_m": xreal,
            "z_range_m": z_range,
            "clean_rms_m": float(clean.std()),
            "degraded_rms_m": float(dirty.std()),
            # Does this image contain REAL periodic structure? The label the
            # real-vs-noise discriminator needs.
            "has_real_periodicity": int(kind in ("grating", "lattice")),
            "n_artifacts": len(applied),
        }
        for name in ARTIFACTS:
            row[name] = int(name in applied)
        for name, params in applied.items():
            for k, v in params.items():
                row[k] = v
        for k, v in truth.items():
            if k != "surface_kind":
                row[k] = v
        rows.append(row)

        if opts["save_gwy"]:
            save_gwy(clean, os.path.join(clean_dir, stem + ".gwy"), xreal, "Height")
            save_gwy(dirty, os.path.join(dirty_dir, stem + ".gwy"), xreal, "Height")

        if (idx + 1) % 25 == 0:
            print("   %d / %d" % (idx + 1, opts["n"]))

    # Union of all keys, since different artifacts contribute different columns.
    columns = ["id", "stem", "surface_kind", "xres", "yres", "xreal_m",
               "z_range_m", "clean_rms_m", "degraded_rms_m",
               "has_real_periodicity", "n_artifacts"] + ARTIFACTS
    extra = set()
    for r in rows:
        extra |= set(r.keys())
    for k in sorted(extra):
        if k not in columns:
            columns.append(k)

    csv_path = os.path.join(out_dir, "labels.csv")
    fh = open(csv_path, "wb")
    try:
        writer = csv.DictWriter(fh, fieldnames=columns, restval="")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    finally:
        fh.close()

    summary = {
        "n_samples": len(rows),
        "size_px": n,
        "seed": opts["seed"],
        "surface_kinds": {},
        "artifact_counts": {},
        "n_with_real_periodicity": sum(r["has_real_periodicity"] for r in rows),
    }
    for r in rows:
        k = r["surface_kind"]
        summary["surface_kinds"][k] = summary["surface_kinds"].get(k, 0) + 1
        for name in ARTIFACTS:
            if r[name]:
                summary["artifact_counts"][name] = \
                    summary["artifact_counts"].get(name, 0) + 1

    json_path = os.path.join(out_dir, "summary.json")
    fh = open(json_path, "w")
    try:
        json.dump(summary, fh, indent=2, sort_keys=True)
    finally:
        fh.close()

    print("")
    print("=" * 58)
    print("Samples          : %d" % summary["n_samples"])
    print("With real periodicity: %d" % summary["n_with_real_periodicity"])
    print("Surface kinds    : %s" % json.dumps(summary["surface_kinds"]))
    print("Artifact counts  : %s" % json.dumps(summary["artifact_counts"]))
    print("Labels           : %s" % csv_path)
    print("Summary          : %s" % json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
