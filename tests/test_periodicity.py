"""
The periodicity measurement, against surfaces whose answer is known.

Every case here is one the previous version got wrong. It reported a repeat on
six scans where the "period" was a little over two pixels -- the sampling limit,
below which an image describes nothing -- and it scored 28 on a single groove
crossing the frame, because one straight edge does resemble a stripe of very
long wavelength.
"""

import numpy as np
import pytest

from afm_copilot.features import MIN_PERIOD_AGREEMENT, periodicity

PIXEL = 10e-9
SIZE = 512


def surface(fn):
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(float)
    return fn(yy, xx)


def noise(scale, seed):
    """Its own generator, so a test never depends on what ran before it."""
    return np.random.default_rng(seed).normal(0, scale, (SIZE, SIZE))


@pytest.mark.parametrize("pitch_px", [8, 20, 74])
def test_grating_pitch_is_recovered(pitch_px):
    data = surface(lambda yy, xx: np.sin(2 * np.pi * xx / pitch_px) * 1e-9)
    result = periodicity(data, PIXEL)
    assert result["period_length"] == pytest.approx(pitch_px * PIXEL, rel=0.05)
    assert result["period_confirmed"] > 1.5


def test_direction_does_not_matter():
    """A grating at 45 degrees must be found as readily as one along an axis."""
    pitch = 20.0
    data = surface(lambda yy, xx:
                   np.sin(2 * np.pi * (xx + yy) / (pitch * np.sqrt(2))) * 1e-9)
    result = periodicity(data, PIXEL)
    assert result["period_length"] == pytest.approx(pitch * PIXEL, rel=0.05)


def test_a_single_step_is_not_periodic():
    """The failure that scored 28 on the scratch scan."""
    data = np.zeros((SIZE, SIZE))
    data[:, SIZE // 3:2 * SIZE // 3] = 20e-9
    assert periodicity(data, PIXEL)["periodicity"] == 0.0


def test_a_single_groove_is_not_periodic():
    data = np.zeros((SIZE, SIZE))
    data[:, 200:300] = -30e-9
    data += noise(0.5e-9, 11)
    assert periodicity(data, PIXEL)["periodicity"] == 0.0


def test_noise_is_not_periodic():
    assert periodicity(noise(1e-9, 12), PIXEL)["periodicity"] == 0.0


def test_two_pixel_structure_is_refused():
    """
    Nothing at the sampling limit counts, however regular it looks.

    A perfect checkerboard is genuinely periodic at two pixels -- and in an AFM
    image that is noise, never surface.
    """
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    data = ((xx + yy) % 2) * 1e-9 + noise(0.2e-9, 13)
    assert periodicity(data, PIXEL)["periodicity"] == 0.0


def test_a_smooth_random_surface_is_not_periodic():
    """
    Rolling hills are not a repeat.

    This is the case that broke the first attempt at a confirmation test: a
    smooth profile does resemble itself a few pixels later, so asking only
    "does it match one period on" passed it. It does not resemble the opposite
    of itself half a period on, which is what separates the two.
    """
    data = noise(1e-9, 14)
    for _ in range(6):
        data = (data + np.roll(data, 1, 0) + np.roll(data, 1, 1)) / 3.0
    assert periodicity(data, PIXEL)["periodicity"] == 0.0


def test_agreement_threshold_is_reported_not_hidden():
    """The confirmation value is part of the answer, so a caller can judge."""
    data = surface(lambda yy, xx: np.sin(2 * np.pi * xx / 16.0) * 1e-9)
    result = periodicity(data, PIXEL)
    assert result["period_confirmed"] >= MIN_PERIOD_AGREEMENT
    assert set(result) >= {"periodicity", "period_angle", "period_length",
                           "period_confirmed"}
