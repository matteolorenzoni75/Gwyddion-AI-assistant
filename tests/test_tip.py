"""
The probe, and what it does to every lateral size.

The arithmetic is checked against the user's own worked example from the sample
catalog: a DNA filament reading 40 nm wide under a 10 nm tip is really 10 nm.
"""

import numpy as np
import pytest

from afm_copilot.tip import (AC160_RADIUS, AC160_RADIUS_COATED, feature_radius,
                             for_scan, sharpest_feature)

SIZE, PIXEL = 256, 2e-9


def spheres(radius, count=14, seed=5, pixel=PIXEL, noise=1e-12):
    """
    Caps of a known radius, which is what the bound has to recover.

    A little noise on purpose: the prominence test measures a summit against
    the noise, and a perfectly noiseless surface has none to measure against.
    """
    yy, xx = (np.mgrid[0:SIZE, 0:SIZE] - SIZE / 2) * pixel
    rng = np.random.default_rng(seed)
    field = rng.normal(0, noise, (SIZE, SIZE))
    for _ in range(count):
        cy, cx = rng.uniform(-SIZE * pixel / 3, SIZE * pixel / 3, 2)
        r2 = (yy - cy) ** 2 + (xx - cx) ** 2
        field = np.maximum(field, np.sqrt(np.clip(radius ** 2 - r2, 0, None)))
    return field


def test_the_catalogs_own_example():
    """40 nm apparent, 10 nm tip, 10 nm radius -- their numbers, exactly."""
    assert feature_radius(40e-9, 10e-9) == pytest.approx(10e-9, rel=1e-6)


def test_a_blunter_tip_makes_a_wider_image():
    """
    Why the assumption has to be stated wherever a width is reported: the same
    particle reads half again as wide through a coated probe.
    """
    apparent_sharp = 4 * np.sqrt(AC160_RADIUS * 25e-9)
    apparent_blunt = 4 * np.sqrt(AC160_RADIUS_COATED * 25e-9)
    assert apparent_blunt > 1.5 * apparent_sharp


def test_the_correction_undoes_the_widening():
    real_radius = 25e-9
    apparent = 4 * np.sqrt(AC160_RADIUS * real_radius)
    assert feature_radius(apparent, AC160_RADIUS) == pytest.approx(
        real_radius, rel=1e-6)


@pytest.mark.parametrize("radius", [10e-9, 20e-9, 40e-9])
def test_the_bound_recovers_a_known_sphere(radius):
    found = sharpest_feature(spheres(radius), PIXEL)
    assert found is not None
    assert found.radius == pytest.approx(radius, rel=0.3)


def test_a_flat_surface_bounds_nothing():
    flat = np.random.default_rng(2).normal(0, 1e-11, (SIZE, SIZE))
    tip = for_scan(flat, PIXEL)
    assert tip.source == "nominal"
    assert tip.radius == AC160_RADIUS


def test_a_loose_bound_does_not_displace_the_nominal():
    """
    An image cannot resolve anything finer than its own pixels, so a scan at
    10 nm per pixel proves only that the tip is no blunter than some hundreds
    of nanometres -- useless against a probe that should be 10 nm. The nominal
    stands, and the bound is kept beside it rather than thrown away.
    """
    coarse = spheres(200e-9, count=10, pixel=20e-9, noise=1e-11)
    tip = for_scan(coarse, 20e-9)
    assert tip.source == "nominal"
    assert tip.radius == AC160_RADIUS
    assert tip.bound is not None and tip.bound > AC160_RADIUS
    assert "no help" in tip.describe()


def test_a_tight_bound_is_used_and_says_so():
    """
    Which needs pixels fine enough to see something sharper than the probe.
    At 2 nm per pixel a 4 nm tip cannot be bounded at all -- the test fixture
    has to sample finely enough for the question to have an answer.
    """
    tip = for_scan(spheres(4e-9, pixel=0.4e-9, noise=1e-13), 0.4e-9)
    assert tip.source == "image"
    assert tip.radius < AC160_RADIUS
    assert "no blunter than" in tip.describe()


def test_a_coated_probe_is_assumed_blunter():
    flat = np.random.default_rng(3).normal(0, 1e-11, (SIZE, SIZE))
    assert for_scan(flat, PIXEL, coated=True).radius == AC160_RADIUS_COATED


def test_a_given_radius_wins_outright():
    tip = for_scan(spheres(4e-9), PIXEL, given=7e-9)
    assert tip.source == "given" and tip.radius == 7e-9
