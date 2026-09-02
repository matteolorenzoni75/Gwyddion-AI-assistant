"""
Known-answer tests for the measurements.

Each surface is built with one property dialled in, so the descriptor meant to
catch it has a right answer. The tests that matter most are the negative ones:
a descriptor that fires on everything is worse than one that fires on nothing,
because it will silently put every sample in the same group.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from afm_copilot.features import (correlation_length, detect_objects,
                                  height_shape, measure, object_statistics,
                                  periodicity, row_banding, row_step_fraction)
from afm_copilot.gwy_io import Channel

N = 256
PIXEL = 20e-9          # 20 nm per pixel -> a 5.12 um scan

# Each generator seeds its own stream. A shared generator would make every
# test's numbers depend on which tests ran before it, so a failure could not be
# reproduced on its own.
def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(20260902 + seed)


def channel(data: np.ndarray) -> Channel:
    return Channel(name="Height", data=data, xreal=N * PIXEL, yreal=N * PIXEL)


def rough(beta: float = 2.5, amplitude: float = 5e-9,
          seed: int = 0) -> np.ndarray:
    """A random surface with no periodicity and no objects."""
    kx = np.fft.fftfreq(N).reshape(1, N)
    ky = np.fft.fftfreq(N).reshape(N, 1)
    k = np.hypot(kx, ky)
    k[0, 0] = 1.0
    spectrum = k ** (-beta / 2.0)
    spectrum[0, 0] = 0.0
    phase = _rng(seed).uniform(0, 2 * np.pi, (N, N))
    surface = np.real(np.fft.ifft2(spectrum * np.exp(1j * phase)))
    return amplitude * surface / surface.std()


def striped(period_px: float, angle_deg: float,
            amplitude: float = 20e-9) -> np.ndarray:
    """Parallel ridges at a chosen angle and spacing."""
    y, x = np.mgrid[0:N, 0:N].astype(float)
    a = math.radians(angle_deg)
    # Stripes run along `angle`, so they repeat along the perpendicular.
    proj = x * math.sin(a) + y * -math.cos(a)
    return amplitude * np.sin(2 * np.pi * proj / period_px)


def particles(count: int = 40, radius_px: float = 6.0,
              height: float = 30e-9, elongation: float = 1.0,
              seed: int = 1) -> np.ndarray:
    rng = _rng(seed)
    out = np.zeros((N, N))
    y, x = np.mgrid[0:N, 0:N].astype(float)
    for _ in range(count):
        cx, cy = rng.uniform(20, N - 20, 2)
        rx = radius_px * elongation
        out += height * np.exp(-(((x - cx) / rx) ** 2 + ((y - cy) / radius_px) ** 2))
    return out


# ------------------------------------------------------------------- lines

def test_banding_is_found_when_rows_are_offset():
    surface = rough()
    banded = surface + _rng(7).normal(0, 8e-9, N)[:, None]
    assert row_banding(banded) > 3 * row_banding(surface)


def test_a_plain_tilt_is_not_called_banding():
    """
    The distinction that matters.

    A slope down the slow axis moves every row mean, but it is form, not a
    line defect. Counting it as banding would mark almost every raw scan.
    """
    y = np.linspace(0, 100e-9, N)[:, None]
    assert row_banding(rough() + y) < 0.05


def test_single_displaced_rows_are_counted():
    surface = rough()
    surface[50, :] += 60e-9
    surface[120, :] -= 60e-9
    assert row_step_fraction(surface) > 0.005


def test_a_clean_surface_has_almost_no_row_steps():
    assert row_step_fraction(rough()) < 0.02


# --------------------------------------------------------------- periodic

@pytest.mark.parametrize("angle", [0, 30, 45, 90, 135])
def test_stripe_direction_is_found_at_any_angle(angle):
    """
    Arbitrary orientation is the point.

    Stripes along the scan axes are the easy case; noise and real structure
    arrive at any angle, and a detector that only sees 0 and 90 degrees is
    useless for both.
    """
    result = periodicity(striped(period_px=16, angle_deg=angle), PIXEL)
    assert result["periodicity"] > 10
    # Direction is modulo 180: 179 degrees and 1 degree are the same stripes.
    error = abs(result["period_angle"] - angle) % 180
    assert min(error, 180 - error) < 12


def test_stripe_spacing_is_recovered():
    result = periodicity(striped(period_px=16, angle_deg=0), PIXEL)
    assert result["period_length"] == pytest.approx(16 * PIXEL, rel=0.2)


def test_a_random_surface_is_not_called_periodic():
    """
    The negative case, and the one that forced the measure to be rewritten.

    Comparing the strongest point of the spectrum against the spectrum as a
    whole makes every rough surface look periodic, because any natural surface
    carries far more energy at low frequencies than at high — so the strongest
    point is simply the largest of the low-frequency terms. Comparing it
    against the other directions at the *same* spatial frequency is what
    separates a repeating structure from ordinary roughness.
    """
    for beta in (1.5, 2.5, 4.0):
        assert periodicity(rough(beta=beta), PIXEL)["periodicity"] < 15


def test_stronger_stripes_score_higher():
    weak = periodicity(rough() + 0.2 * striped(16, 20), PIXEL)["periodicity"]
    strong = periodicity(rough() + 5.0 * striped(16, 20), PIXEL)["periodicity"]
    assert strong > weak


# ---------------------------------------------------------------- objects

def test_particles_are_counted_and_sized():
    mask = detect_objects(particles(count=25, radius_px=6))
    stats = object_statistics(mask, PIXEL)
    assert 10 <= stats["object_count"] <= 40          # some will overlap
    assert 40e-9 < stats["object_median_size"] < 400e-9


def test_rods_read_as_elongated_and_particles_do_not():
    round_stats = object_statistics(
        detect_objects(particles(count=20, elongation=1.0)), PIXEL)
    rod_stats = object_statistics(
        detect_objects(particles(count=20, elongation=4.0)), PIXEL)
    assert rod_stats["object_elongation"] > round_stats["object_elongation"] * 1.5


def test_roughness_peaks_are_not_taken_for_objects():
    """
    A rough surface has high points, and they are not objects.

    They are caught as small specks, so what has to stay low is the *fraction*
    of the frame they cover — that is the number the decision uses, and it must
    sit below the level that would trigger the masked recipe.
    """
    assert detect_objects(rough()).mean() < 0.03


# ---------------------------------------------------------------- texture

def test_correlation_length_grows_with_feature_size():
    fine = correlation_length(rough(beta=1.5), PIXEL)
    broad = correlation_length(rough(beta=4.0), PIXEL)
    assert broad > fine


def test_particles_on_a_flat_base_are_skewed_upward():
    """Objects on a flat surface push the height distribution one way."""
    assert height_shape(particles())["skewness"] > 0.5


def test_a_random_surface_is_not_skewed():
    """A surface built from random phases has no preferred direction."""
    for seed in (0, 2, 3):
        assert abs(height_shape(rough(seed=seed))["skewness"]) < 0.6


def test_two_levels_read_as_bimodal():
    surface = rough(amplitude=1e-9)
    surface[:, : N // 2] += 40e-9
    plain = height_shape(rough())["bimodality"]
    split = height_shape(surface)["bimodality"]
    assert split > plain


# ------------------------------------------------------------------- all

def test_measuring_a_scan_fills_every_group():
    f = measure(channel(rough() + striped(20, 35) * 0.3 + particles(count=10)))
    assert f.scan_size == pytest.approx(N * PIXEL)
    assert f.pixel_size == pytest.approx(PIXEL)
    assert f.rms > 0
    assert f.periodicity > 0
    assert not math.isnan(f.period_angle)


def test_the_background_is_removed_before_measuring():
    """
    A tilt must not change the texture measurements.

    If it did, every descriptor would depend on how the sample happened to sit
    on the stage, and nothing could be compared between scans.
    """
    surface = rough() + particles(count=15)
    y, x = np.mgrid[0:N, 0:N].astype(float) / N
    tilted = surface + 300e-9 * x

    a = measure(channel(surface))
    b = measure(channel(tilted))

    assert b.rms == pytest.approx(a.rms, rel=0.15)
    assert b.object_fraction == pytest.approx(a.object_fraction, abs=0.03)
    # The tilt itself is still reported, as its own number.
    assert b.tilt > 0.5 and a.tilt < 0.2
