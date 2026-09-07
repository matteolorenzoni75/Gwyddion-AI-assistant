"""
Choosing the colour range from what the picture is of.

The image is what leaves the lab, so the range it is drawn with is a
measurement decision, not a cosmetic one. These tests pin the case the guided
range exists for -- and, just as importantly, the cases where it must stand
aside, because the ordinary percentile range is right far more often than not.
"""

import numpy as np
import pytest

from afm_copilot.gwy_io import Channel
from afm_copilot.render import common_color_scale, guided_color_scale

N = 256


def textured(roughness=2e-9, seed=4):
    data = np.random.default_rng(seed).normal(0, 1e-9, (N, N))
    for _ in range(6):
        data = (data + np.roll(data, 1, 0) + np.roll(data, 1, 1)) / 3.0
    return data * (roughness / max(data.std(), 1e-18))


def channel(data):
    return Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6)


def with_towers(height=200e-9):
    yy, xx = np.mgrid[0:N, 0:N]
    data = textured()
    data[(yy - 80) ** 2 + (xx - 90) ** 2 < 28 ** 2] += height
    data[(yy - 180) ** 2 + (xx - 170) ** 2 < 18 ** 2] += height * 0.75
    return data


def test_a_towering_object_gives_the_range_back_to_the_surface():
    """
    The failure this exists for: 2 nm of texture under a 200 nm object gets one
    hundredth of the colour scale and disappears.
    """
    ch = channel(with_towers())
    plain = common_color_scale([ch])
    guided, note = guided_color_scale(ch)

    assert note["guided"]
    assert guided.span < plain.span / 4, "the range must narrow, not widen"
    assert 0.01 < note["clipped"] < 0.15, "the towers saturate, nothing else"
    assert "tower over" in note["reason"]


def test_modest_features_are_left_alone():
    """
    Narrowing costs real information, so it has to be earned. Objects only a
    little taller than the texture are shown perfectly well by the ordinary
    range.
    """
    ch = channel(with_towers(height=4e-9))
    plain = common_color_scale([ch])
    guided, note = guided_color_scale(ch)
    assert not note["guided"]
    assert guided.vmin == pytest.approx(plain.vmin, rel=1e-6)
    assert guided.vmax == pytest.approx(plain.vmax, rel=1e-6)


def test_a_bare_surface_is_left_alone():
    """
    Whether the detector finds nothing at all or finds only the texture's own
    high points, the answer is the same: leave the range alone.
    """
    _, note = guided_color_scale(channel(textured()))
    assert not note["guided"]
    assert note["reason"]


def test_a_frame_that_is_all_object_is_left_alone():
    """With no background there is nothing to protect."""
    yy, xx = np.mgrid[0:N, 0:N]
    data = textured()
    data[yy > 40] += 200e-9
    _, note = guided_color_scale(channel(data))
    assert not note["guided"]


def test_pits_narrow_the_other_way():
    ch = channel(-with_towers())
    guided, note = guided_color_scale(ch)
    assert note["guided"] and "pits" in note["reason"]


@pytest.mark.parametrize("roughness", [1e-9, 8e-9, 40e-9])
def test_guided_never_widens_the_range(roughness):
    """
    The invariant, and it had to be learned the hard way.

    Reaching a margin above the background to keep the features from becoming
    a flat silhouette can overshoot the ordinary percentile on a rough surface,
    and then the "guided" range is *wider* than the plain one -- darker
    pictures with less detail, which is exactly the failure this function
    exists to prevent. It fired that way on four of the first six real scans
    it touched.
    """
    ch = channel(with_towers(height=200e-9) + textured(roughness, seed=9))
    plain = common_color_scale([ch])
    guided, _ = guided_color_scale(ch)
    assert guided.vmin >= plain.vmin - 1e-15
    assert guided.vmax <= plain.vmax + 1e-15


def test_the_decision_always_explains_itself():
    """Every range carries the sentence that justifies it."""
    for data in (textured(), with_towers(), -with_towers()):
        _, note = guided_color_scale(channel(data))
        assert note["reason"] and not note["reason"].endswith(":")
        assert 0.0 <= note["clipped"] <= 1.0
