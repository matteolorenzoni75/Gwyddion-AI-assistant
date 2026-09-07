"""
Corrections that apply to a region rather than the frame.

The user reports these are frequent: a dish left where the tip dragged, a patch
of dirt. The distinction that matters is between pixels that are not
measurements at all -- erased and filled -- and pixels that are measurements
sitting at the wrong height, which have to be lifted back with their texture
intact.
"""

import numpy as np
import pytest

from afm_copilot.repair import find_dishes, lift_region

N = 256


def textured(roughness=2e-9, seed=3):
    data = np.random.default_rng(seed).normal(0, 1e-9, (N, N))
    for _ in range(6):
        data = (data + np.roll(data, 1, 0) + np.roll(data, 1, 1)) / 3.0
    return data * (roughness / max(data.std(), 1e-18))


def dish(depth=40e-9, radius=60):
    """A broad sag, as the tip leaves when it drags and recovers slowly."""
    yy, xx = np.mgrid[0:N, 0:N]
    r2 = ((yy - 90) ** 2 + (xx - 90) ** 2) / float(radius ** 2)
    return -depth * np.clip(1.0 - r2, 0.0, None)


def test_a_dish_is_lifted_back():
    surface = textured()
    damaged = surface + dish()
    region = find_dishes(damaged)
    assert region.sum() > 400, "the dish has to be found first"

    fixed = lift_region(damaged, region)
    # What is left inside should sit near the surrounding level again.
    inside = region
    before = abs(float(np.median(damaged[inside]) - np.median(damaged[~inside])))
    after = abs(float(np.median(fixed[inside]) - np.median(fixed[~inside])))
    assert after < before / 3


def test_the_texture_inside_survives():
    """
    The whole reason not to erase it: those pixels are the sample.
    """
    surface = textured()
    damaged = surface + dish()
    region = find_dishes(damaged)
    fixed = lift_region(damaged, region)

    kept = np.std(fixed[region])
    original = np.std(surface[region])
    assert kept == pytest.approx(original, rel=0.5)


def test_nothing_outside_the_region_moves():
    surface = textured()
    damaged = surface + dish()
    region = find_dishes(damaged)
    fixed = lift_region(damaged, region)
    assert np.allclose(fixed[~region], damaged[~region])


def test_a_speck_is_not_this_kind_of_repair():
    """
    Small defects belong to the erase-and-fill route. Lifting a handful of
    pixels to match their surroundings would just move a speck.
    """
    surface = textured()
    speck = np.zeros((N, N), dtype=bool)
    speck[100:105, 100:105] = True
    assert np.allclose(lift_region(surface, speck), surface)


def test_a_clean_surface_has_no_dishes():
    assert find_dishes(textured()).sum() == 0


def test_sharp_pits_are_not_mistaken_for_dishes():
    """
    A pore has steep walls and a floor; a dragged dish sags. The detector
    looks at a heavily smoothed surface, which is blind to anything sharp.
    """
    surface = textured()
    yy, xx = np.mgrid[0:N, 0:N]
    rng = np.random.default_rng(8)
    for _ in range(25):
        cy, cx = rng.integers(20, N - 20, 2)
        surface[(yy - cy) ** 2 + (xx - cx) ** 2 < 36] -= 30e-9
    assert find_dishes(surface).sum() == 0
