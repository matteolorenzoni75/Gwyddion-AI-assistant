"""
Known-answer tests for the step and thickness measurements.

These build surfaces whose true step height is known exactly, then check the
measurement recovers it. The refusal cases matter as much as the successful
ones: a measurement that confidently reports a step on a surface that has none
is the failure mode worth guarding against.
"""

from __future__ import annotations

import numpy as np
import pytest

from afm_copilot.analysis import (MAX_PLANE_FRACTION, MIN_SEPARABILITY,
                                  aggregate, measure_film_thickness,
                                  measure_step, measure_step_iso5436)
from afm_copilot.gwy_io import Channel
from afm_copilot.profile import extract_profile, profile_across

RNG = np.random.default_rng(20260831)


def make_film_with_scratch(
    thickness: float = 40e-9,
    scratch_fraction: float = 0.3,
    roughness: float = 1e-9,
    n: int = 256,
) -> Channel:
    """A flat film on a substrate, with a scratch exposing the substrate."""
    data = np.full((n, n), thickness, dtype=float)
    width = int(n * scratch_fraction)
    data[:, :width] = 0.0
    data += RNG.normal(0.0, roughness, (n, n))
    return Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6,
                   z_unit="m", xy_unit="m")


def test_recovers_known_thickness():
    truth = 40e-9
    channel = make_film_with_scratch(thickness=truth, roughness=1e-9)
    result = measure_film_thickness(channel)

    assert result.ok, result.warnings
    assert result.value == pytest.approx(truth, rel=0.02)
    # The two levels are 40 nm apart with 1 nm scatter, so they should be
    # separated by far more than the minimum ratio.
    assert result.separation_ratio > 10


def test_recovers_thin_film_close_to_noise():
    """A 5 nm film on a 1 nm-rough surface is still measurable, but tighter."""
    truth = 5e-9
    channel = make_film_with_scratch(thickness=truth, roughness=1e-9)
    result = measure_film_thickness(channel)

    assert result.ok, result.warnings
    assert result.value == pytest.approx(truth, rel=0.10)


def test_refuses_when_there_is_no_step():
    """
    A featureless rough surface must not yield a confident step height.

    This is the case a naive threshold-and-subtract would get wrong: Otsu
    happily splits a Gaussian in half, and the two halves' medians differ by
    ~2.2x their scatter, so a separation ratio alone would call it a step.
    """
    data = RNG.normal(0.0, 2e-9, (256, 256))
    channel = Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6)

    result = measure_film_thickness(channel)

    assert not result.ok
    assert result.warnings
    # A single Gaussian population sits near 0.64 separability.
    assert result.separability < MIN_SEPARABILITY


def test_refuses_when_tilt_swamps_the_step():
    """
    An unlevelled image must be rejected rather than measured.

    A strong tilt spreads both populations until they merge -- exactly the case
    where a naive histogram measurement would return a confident, wrong number.
    """
    channel = make_film_with_scratch(thickness=10e-9, roughness=0.5e-9)
    n = channel.data.shape[0]
    ramp = np.linspace(0, 200e-9, n)
    channel.data = channel.data + ramp[None, :]

    result = measure_film_thickness(channel)

    assert not result.ok
    # The residual-tilt test must catch this before the histogram is even
    # consulted: separability alone scores this case ABOVE a genuine 20 nm
    # step, so relying on it would accept the unmeasurable image.
    assert result.plane_fraction >= MAX_PLANE_FRACTION
    # The advice has to be actionable: this image needs levelling, and the
    # message should say so rather than just declining.
    assert any("level" in w.lower() for w in result.warnings)


def test_tilt_test_catches_what_separability_misses():
    """
    The case that forced two criteria instead of one.

    A mild ramp plus a real step scores 0.82 separability -- higher than a
    genuine 20 nm step on 5 nm roughness, which scores 0.79. A single
    separability threshold would therefore accept the wrong one and reject the
    right one. Only the plane-fraction test distinguishes them.
    """
    tilted = make_film_with_scratch(thickness=10e-9, roughness=0.5e-9)
    n = tilted.data.shape[0]
    tilted.data = tilted.data + np.linspace(0, 30e-9, n)[None, :]

    genuine = make_film_with_scratch(thickness=20e-9, roughness=5e-9)

    tilted_result = measure_film_thickness(tilted)
    genuine_result = measure_film_thickness(genuine)

    assert not tilted_result.ok
    assert genuine_result.ok
    assert genuine_result.value == pytest.approx(20e-9, rel=0.15)


def test_warns_when_scratch_is_tiny():
    """A scratch covering 1% of the frame is measured, but flagged."""
    channel = make_film_with_scratch(thickness=30e-9, scratch_fraction=0.01,
                                     roughness=0.5e-9)
    result = measure_film_thickness(channel)

    assert result.ok
    assert any("too little" in w for w in result.warnings)


def test_iso5436_on_a_profile():
    channel = make_film_with_scratch(thickness=25e-9, roughness=0.5e-9)
    prof = profile_across(channel, "horizontal", band_px=5)

    result = measure_step_iso5436(prof, source="synthetic")

    assert result.ok, result.warnings
    assert result.value == pytest.approx(25e-9, rel=0.05)


def test_profile_geometry_and_units():
    channel = make_film_with_scratch()
    prof = extract_profile(channel, (0.0, 0.5), (1.0, 0.5))

    # A full-width horizontal profile spans the whole scan.
    assert prof.length == pytest.approx(channel.xreal, rel=0.01)
    assert prof.n_points == channel.data.shape[1]


def test_band_averaging_reduces_noise():
    channel = make_film_with_scratch(roughness=2e-9)
    single = profile_across(channel, "horizontal", band_px=1)
    banded = profile_across(channel, "horizontal", band_px=16)

    # Within the flat film region, averaging 16 rows should visibly reduce
    # scatter -- roughly by sqrt(16), so require at least a factor of two.
    tail = slice(int(0.6 * single.n_points), None)
    assert np.std(banded.height[tail]) < np.std(single.height[tail]) / 2


def test_aggregate_pools_and_reports_rejections():
    good = [measure_film_thickness(make_film_with_scratch(thickness=t))
            for t in (40e-9, 42e-9, 38e-9)]
    bad = measure_step(RNG.normal(0, 1e-9, (256, 256)), source="flat.gwy")

    result = aggregate(good + [bad])

    assert result.n_used == 3
    assert result.n_total == 4
    assert result.mean == pytest.approx(40e-9, rel=0.05)
    assert result.std > 0
    assert len(result.rejected) == 1
    assert result.rejected[0][0] == "flat.gwy"

