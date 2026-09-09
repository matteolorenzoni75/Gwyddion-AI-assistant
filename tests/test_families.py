"""
Terrace heights from the height histogram, and the family a scan belongs to.

The user's condition is the specification: two or three well-defined Gaussian
peaks in the height histogram, and only then are the spacings between them
terrace heights. So the cases that matter most here are the surfaces that must
NOT produce peaks -- a single rough population, a tilt, a gradual slope -- and
the family rule must be equally reluctant: a pile is a claim about what the
sample is, and a wrong one costs more than 'other'.
"""

from __future__ import annotations

import numpy as np
import pytest

from afm_copilot.analysis import (Reading, background_roughness, family_of,
                                  height_levels, readings_for)
from afm_copilot.gwy_io import Channel


def terraced(steps: list[float], roughness: float = 0.4e-9,
             n: int = 256, seed: int = 7) -> Channel:
    """A staircase: equal-width bands, each `steps[i]` above the previous."""
    rng = np.random.default_rng(seed)
    heights = np.concatenate(([0.0], np.cumsum(steps)))
    data = np.zeros((n, n), dtype=float)
    edges = np.linspace(0, n, len(heights) + 1).astype(int)
    for level, (start, stop) in zip(heights, zip(edges[:-1], edges[1:])):
        data[:, start:stop] = level
    data += rng.normal(0.0, roughness, (n, n))
    return Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6,
                   z_unit="m", xy_unit="m")


def rough(rms: float = 5e-9, n: int = 256, seed: int = 11) -> Channel:
    rng = np.random.default_rng(seed)
    return Channel(name="Height", data=rng.normal(0.0, rms, (n, n)),
                   xreal=5e-6, yreal=5e-6, z_unit="m", xy_unit="m")


def test_three_terraces_give_two_spacings():
    channel = terraced([12e-9, 12e-9])
    levels = height_levels(channel)

    assert len(levels) == 3
    gaps = np.diff(levels)
    assert gaps == pytest.approx([12e-9, 12e-9], rel=0.08)


def test_uneven_terraces_are_reported_separately():
    channel = terraced([8e-9, 25e-9])
    gaps = np.diff(height_levels(channel))

    assert gaps == pytest.approx([8e-9, 25e-9], rel=0.10)


def test_one_rough_population_has_no_levels():
    # The single most important negative: a Gaussian surface has exactly one
    # peak, and quoting a terrace height for it would be a number about
    # nothing.
    assert height_levels(rough()) == []


def test_a_tilt_has_no_levels():
    n = 256
    ramp = np.tile(np.linspace(0.0, 60e-9, n), (n, 1))
    channel = Channel(name="Height", data=ramp, xreal=5e-6, yreal=5e-6,
                      z_unit="m", xy_unit="m")

    assert height_levels(channel) == []


def test_steps_buried_in_noise_are_not_levels():
    # Terraces one third of the roughness are not "well-defined peaks", and
    # the histogram should stay one hump.
    assert height_levels(terraced([2e-9, 2e-9], roughness=6e-9)) == []


def test_terraces_reach_the_readings_as_a_thickness():
    channel = terraced([15e-9, 15e-9])
    readings = readings_for(channel, {}, None)
    thickness = [r for r in readings if r.kind == "thickness"]

    assert thickness, [r.headline for r in readings]
    assert "terraces at" in thickness[0].headline
    assert family_of(readings, {}) == "terraces"


def test_a_field_of_round_particles_is_named_as_one():
    measurements = {"object_count": 40, "object_polarity": 1,
                    "object_median_size": 60e-9, "object_size_spread": 0.18,
                    "object_elongation": 1.1, "object_fraction": 0.22,
                    "rms": 8e-9}
    readings = readings_for(rough(), measurements, 10e-9)
    particles = [r for r in readings if r.kind == "particles"]

    assert particles, [r.headline for r in readings]
    assert "nanoparticle layer" in particles[0].headline
    assert family_of(readings, measurements) == "particles"


def test_few_or_elongated_objects_are_not_called_a_particle_layer():
    # The attribution rule the user set is ">5 spherical objects". Four
    # objects, or forty elongated ones, do not earn the name -- they keep the
    # neutral word and the neutral pile.
    for measurements in (
            {"object_count": 4, "object_polarity": 1,
             "object_median_size": 60e-9, "object_size_spread": 0.15,
             "object_elongation": 1.1, "object_fraction": 0.05},
            {"object_count": 40, "object_polarity": 1,
             "object_median_size": 60e-9, "object_size_spread": 0.15,
             "object_elongation": 2.8, "object_fraction": 0.22},
            {"object_count": 40, "object_polarity": 1,
             "object_median_size": 60e-9, "object_size_spread": 0.60,
             "object_elongation": 1.1, "object_fraction": 0.22}):
        readings = readings_for(rough(), measurements, 10e-9)
        headlines = " ".join(r.headline for r in readings)
        assert "nanoparticle layer" not in headlines, measurements
        assert family_of(readings, measurements) != "particles"


def test_recessed_objects_land_in_the_pits_pile():
    measurements = {"object_count": 30, "object_polarity": -1,
                    "object_median_size": 80e-9, "object_size_spread": 0.2,
                    "object_elongation": 1.1, "object_fraction": 0.2}
    readings = readings_for(rough(), measurements, 10e-9)

    assert family_of(readings, measurements) == "pits"


def test_nothing_measurable_is_its_own_pile():
    assert family_of([], {}) == "other"


def scattered_bumps(count: int = 60, n: int = 256, height: float = 30e-9,
                    seed: int = 3) -> Channel:
    """Small round objects on a flat substrate -- a minority population."""
    rng = np.random.default_rng(seed)
    data = rng.normal(0.0, 1e-9, (n, n))
    ys, xs = np.mgrid[0:n, 0:n]
    for cy, cx in rng.integers(12, n - 12, size=(count, 2)):
        data += height * np.exp(-(((ys - cy) ** 2 + (xs - cx) ** 2) / 18.0))
    return Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6,
                   z_unit="m", xy_unit="m")


def test_a_minority_of_objects_is_not_a_step():
    # The user's objection in one test: the histogram splits cleanly here --
    # substrate and bump tops -- and it is still not a step, because the raised
    # population holds a few per cent of the surface.
    channel = scattered_bumps()
    measurements = {"bimodality": 0.85, "object_count": 60,
                    "object_polarity": 1, "object_median_size": 40e-9,
                    "object_size_spread": 0.2, "object_elongation": 1.1,
                    "object_fraction": 0.06, "rms": 6e-9}
    readings = readings_for(channel, measurements, 10e-9)

    assert not any(r.headline.startswith("step ") for r in readings), \
        [r.headline for r in readings]
    assert family_of(readings, measurements) != "terraces"


def test_many_separate_pieces_never_make_a_step():
    # Even where the surface share would pass, dozens of separate pieces are a
    # scattering. This is the fibre network that was reported as a 35 nm step.
    channel = terraced([20e-9])
    measurements = {"bimodality": 0.90, "object_count": 51,
                    "object_polarity": 1, "object_fraction": 0.40}
    readings = readings_for(channel, measurements, None)

    assert not any(r.headline.startswith(("step ", "terraces at"))
                   for r in readings), [r.headline for r in readings]


def test_a_handful_of_grains_does_not_block_a_real_step():
    # The other side of the same rule: a stepped film carrying a few grains is
    # still a stepped film.
    channel = terraced([20e-9])
    measurements = {"bimodality": 0.90, "object_count": 7,
                    "object_polarity": 1, "object_fraction": 0.10}
    readings = readings_for(channel, measurements, None)

    assert any(r.headline.startswith("step ") for r in readings), \
        [r.headline for r in readings]


def test_a_refusal_is_not_overruled():
    # A scan whose heights look split but which the step routine rejects must
    # report the refusal, never a number from a weaker test.
    channel = rough(rms=20e-9)
    readings = readings_for(channel, {"bimodality": 0.80}, None)

    for reading in readings:
        assert not reading.headline.startswith("step "), reading.headline


def test_a_few_specks_get_the_background_roughness():
    # The gap this closes: three objects on an otherwise even substrate. Too
    # busy for the whole-frame roughness, too few to count. The answer is the
    # roughness of the surface with the objects left out.
    channel = scattered_bumps(count=3, height=60e-9)
    measurements = {"object_count": 3, "object_polarity": 1,
                    "object_fraction": 0.05, "bimodality": 0.2, "rms": 9e-9}
    readings = readings_for(channel, measurements, None)
    roughness = [r for r in readings if r.kind == "roughness"]

    assert roughness, [r.headline for r in readings]
    assert "background alone" in roughness[0].detail
    assert family_of(readings, measurements) == "uniform"


def test_the_background_roughness_is_below_the_whole_frame_one():
    # And it has to be the smaller number, or it is not measuring what it says.
    channel = scattered_bumps(count=3, height=60e-9)
    whole = float(np.std(np.asarray(channel.data)))
    sq, share = background_roughness(channel)

    assert sq < whole
    assert 0.0 <= share < 0.5


def test_a_field_of_particles_gets_no_background_roughness():
    # The guard that matters lives in the caller, not in the measurement: with
    # a field of particles what lies between them is the gaps, not a surface,
    # and the scan's answer is how many and how big -- not how smooth the gaps
    # are.
    channel = scattered_bumps(count=60)
    measurements = {"object_count": 60, "object_polarity": 1,
                    "object_fraction": 0.20, "bimodality": 0.2,
                    "object_median_size": 40e-9, "object_size_spread": 0.2,
                    "object_elongation": 1.1, "rms": 9e-9}
    readings = readings_for(channel, measurements, None)

    assert not any(r.kind == "roughness" for r in readings), \
        [r.headline for r in readings]
    assert any(r.kind == "particles" for r in readings)


def test_a_clean_surface_still_gets_the_whole_frame_roughness():
    # The new branch must not displace the old one.
    readings = readings_for(rough(rms=3e-9),
                            {"object_fraction": 0.0, "bimodality": 0.1,
                             "rms": 3e-9}, None)
    roughness = [r for r in readings if r.kind == "roughness"]

    assert roughness
    assert "whole frame" in roughness[0].detail


def test_a_lattice_outranks_loose_objects():
    readings = [Reading("particles", "objects, 50 nm across"),
                Reading("pattern", "period 120 nm")]

    assert family_of(readings, {"object_polarity": 1}) == "pattern"
