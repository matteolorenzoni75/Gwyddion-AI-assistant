"""
Finding what departs from the surface, in both directions.

Looking only upwards made a porous surface and a smooth one identical: on three
pitted scans of the real pool the count reported zero objects against dozens of
obvious holes. The tests below are the cases that failed, plus the ones that
must not break in fixing them.
"""

import numpy as np
import pytest

from afm_copilot.decide import detect_features, detect_objects
from afm_copilot.features import measure
from afm_copilot.gwy_io import Channel

SIZE = 256


def flat(seed=1, roughness=1e-9):
    data = np.random.default_rng(seed).normal(0, roughness, (SIZE, SIZE))
    for _ in range(8):
        data = (data + np.roll(data, 1, 0) + np.roll(data, 1, 1)) / 3.0
    return data * (roughness / max(data.std(), 1e-18))


def blobs(data, count=12, radius=8, height=20e-9):
    """Round features of a given sign, scattered without overlapping much."""
    rng = np.random.default_rng(4)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    out = data.copy()
    for _ in range(count):
        cy, cx = rng.integers(radius, SIZE - radius, 2)
        out[(yy - cy) ** 2 + (xx - cx) ** 2 <= radius ** 2] += height
    return out


def channel(data):
    return Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6)


def test_holes_are_found():
    """The failure this exists for: pits were invisible."""
    above, below = detect_features(blobs(flat(), height=-20e-9))
    assert below.mean() > 0.005
    assert above.mean() < 0.002


def test_bumps_are_still_found():
    above, below = detect_features(blobs(flat(), height=+20e-9))
    assert above.mean() > 0.005
    assert below.mean() < 0.002


def test_a_bare_surface_has_neither():
    above, below = detect_features(flat())
    assert above.mean() < 0.01
    assert below.mean() < 0.01


def test_the_mask_for_a_background_fit_holds_both():
    """
    A pit distorts a fitted background exactly as a bump does.

    Excluding one and not the other is half a correction.
    """
    data = blobs(blobs(flat(), count=6, height=+20e-9), count=6, height=-20e-9)
    mask = detect_objects(data)
    above, below = detect_features(data)
    assert mask.sum() == (above | below).sum()
    assert above.any() and below.any()


def test_polarity_says_which_way():
    pitted = measure(channel(blobs(flat(), height=-20e-9)))
    raised = measure(channel(blobs(flat(), height=+20e-9)))
    assert pitted.object_polarity == -1
    assert raised.object_polarity == +1
    assert pitted.sunken_fraction > pitted.raised_fraction
    assert raised.raised_fraction > raised.sunken_fraction


def test_polarity_stays_silent_when_both_sides_are_alike():
    both = blobs(blobs(flat(), count=8, height=+20e-9), count=8, height=-20e-9)
    assert measure(channel(both)).object_polarity == 0


def test_sizes_are_measured_on_the_side_that_has_the_features():
    """
    Averaging a grain's diameter with a pore's would describe neither.
    """
    pitted = measure(channel(blobs(flat(), count=12, radius=8,
                                   height=-20e-9)))
    assert pitted.object_count >= 8
    # Equivalent diameter of a radius-8 disc, in metres, within a wide margin.
    expected = 2 * 8 * (5e-6 / SIZE)
    assert pitted.object_median_size == pytest.approx(expected, rel=0.5)


def test_a_leftover_bow_is_not_an_object():
    """
    One connected piece covering much of the frame is background, not a
    feature -- and masking it would starve the next background fit.
    """
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(float)
    bow = flat() + 3e-8 * ((xx / SIZE - 0.5) ** 2 + (yy / SIZE - 0.5) ** 2)
    above, below = detect_features(bow)
    assert above.mean() < 0.05
    assert below.mean() < 0.05


def test_noise_alone_never_makes_features():
    """
    A polished substrate has a tiny height range, and a purely proportional
    threshold lands inside its own noise.
    """
    noise = np.random.default_rng(3).normal(0, 3e-11, (SIZE, SIZE))
    above, below = detect_features(noise)
    assert above.mean() < 0.01
    assert below.mean() < 0.01
