"""
The gate that decides whether a scan is worth using.

Calibrated on 161 real scans. The first version discarded 19% of them,
including the DVD that had just measured the scanner correctly -- so the rules
below are as much about what must NOT be thrown away as about what must.
"""

import numpy as np
import pytest

from afm_copilot.gwy_io import Channel
from afm_copilot.quality import assess, noise_level

SIZE = 256


def channel(data):
    return Channel(name="Height", data=data, xreal=10e-6, yreal=10e-6)


def surface(seed=1, roughness=5e-9, smoothness=20):
    """
    A plausible surface: correlated over several pixels, not white noise.

    The smoothing matters and the first version of this fixture did not have
    enough of it. Four passes leaves a surface whose height still changes
    substantially from one pixel to the next, and the noise check called that
    noisy -- correctly, since on real data only three scans in a hundred and
    sixty-one trip it. The fixture was wrong, not the threshold.
    """
    data = np.random.default_rng(seed).normal(0, roughness, (SIZE, SIZE))
    for _ in range(smoothness):
        data = (data + np.roll(data, 1, 0) + np.roll(data, 1, 1)) / 3.0
    return data * (roughness / max(data.std(), 1e-18))


def test_a_clean_scan_passes():
    assert assess(channel(surface())).verdict == "good"


def test_a_tilted_scan_is_still_clean():
    """Tilt is not a fault. It is removed before anything is judged."""
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    tilted = surface() + xx * 1e-9
    assert assess(channel(tilted)).verdict == "good"


def test_mostly_noise_is_kept_and_flagged():
    """
    Noise used to be fatal on its own, and that was wrong.

    A scan of HOPG was thrown away for it whose terraces were perfectly good --
    the user's verdict was that it is noisy and entirely recoverable, the noise
    being the only thing wrong with it. Something that can be filtered is not a
    reason to discard; it is a reason to filter.
    """
    data = np.random.default_rng(3).normal(0, 5e-9, (SIZE, SIZE))
    verdict = assess(channel(data))
    assert verdict.verdict == "fixable"
    assert any(c.name == "noise" and c.is_bad for c in verdict.checks)


def test_an_empty_frame_is_still_fatal_on_its_own():
    """The one case where there is genuinely nothing to work with."""
    data = surface()
    data[30:, :] = data[29, 0]
    assert assess(channel(data)).verdict == "discard"


def test_an_empty_frame_is_discarded():
    data = surface()
    data[40:, :] = data[39, 0]              # the scan stopped after 40 rows
    assert assess(channel(data)).verdict == "discard"


def test_a_scan_that_stopped_late_is_kept_and_cropped():
    data = surface()
    data[200:, :] = data[199, 0]            # 22% empty
    verdict = assess(channel(data))
    assert verdict.verdict == "fixable"
    assert any("cropped" in c.says for c in verdict.problems)


def test_row_offsets_are_reported_as_fixable():
    data = surface()
    data += np.random.default_rng(5).normal(0, 3e-9, (SIZE, 1))
    verdict = assess(channel(data))
    assert verdict.verdict == "fixable"
    assert any(c.name == "banding" for c in verdict.problems)


def test_flat_plateaux_are_not_called_saturation():
    """
    The failure that discarded a DVD.

    A lithographic pattern has flat levels by design. Real clipping writes the
    identical number over and over; a pit floor does not.
    """
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    pattern = ((xx // 16) % 2).astype(float) * 30e-9
    pattern += surface(seed=7, roughness=0.5e-9)
    verdict = assess(channel(pattern))
    assert verdict.verdict != "discard"
    assert not any(c.name == "saturation" and c.is_bad
                   for c in verdict.checks)


def test_real_clipping_is_caught():
    data = surface(roughness=20e-9)
    ceiling = np.percentile(data, 80)
    data = np.minimum(data, ceiling)        # 20% pinned at one value
    assert any(c.name == "saturation" and c.is_bad
               for c in assess(channel(data)).checks)


def test_one_complaint_alone_does_not_discard():
    """
    Discarding takes more than one opinion.

    Every check here misfires on some legitimate surface, so a single bad
    signal means "look at it", not "throw it away". Only an empty frame or an
    image that is mostly noise is fatal on its own.
    """
    data = surface(roughness=20e-9)
    data = np.minimum(data, np.percentile(data, 80))
    verdict = assess(channel(data))
    bad = [c for c in verdict.checks if c.is_bad]
    assert len(bad) == 1
    assert verdict.verdict == "fixable"


def test_every_complaint_says_something_a_person_can_read():
    data = surface()
    data[200:, :] = data[199, 0]
    for check in assess(channel(data)).checks:
        assert check.says and not check.says.endswith(":")
        assert check.verdict in {"ok", "fixable", "bad"}


def test_height_that_rattles_on_the_features_is_reported():
    """
    Noise that lives on part of the frame while the rest stays quiet.

    A global measure cannot see it: on the scan this came from, the drop
    rattles by 9 nm and the rest of the frame by 0.4, and averaged together
    they are unremarkable.
    """
    data = surface(roughness=2e-9)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    blob = (yy - 90) ** 2 + (xx - 90) ** 2 < 45 ** 2
    data[blob] += 30e-9
    # The tip flipping regime: alternate pixels pushed apart, on the blob only.
    data[blob & (xx % 2 == 0)] += 4e-9
    data[blob & (xx % 2 == 1)] -= 4e-9

    verdict = assess(channel(data))
    rattle = next(c for c in verdict.checks if c.name == "rattle")
    assert rattle.verdict == "fixable"
    assert "alternates" in rattle.says


def test_a_steady_surface_with_objects_does_not_rattle():
    """A particle's edge departs from a straight line too, but only once."""
    data = surface(roughness=2e-9)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    data[(yy - 90) ** 2 + (xx - 90) ** 2 < 45 ** 2] += 30e-9
    rattle = next(c for c in assess(channel(data)).checks if c.name == "rattle")
    assert rattle.verdict == "ok"


def test_the_dead_band_is_not_judged():
    """
    Checks run on the part that has data.

    A dead band's edge reads as a step, its interior as saturation, and its
    border with the live data rattles -- five scans in a real batch were
    flagged for nothing but where they stopped.
    """
    data = surface()
    data[200:, :] = data[199, 0]
    verdict = assess(channel(data))
    assert verdict.verdict == "fixable"
    assert not any(c.is_bad for c in verdict.checks)


def test_noise_level_ignores_real_steps():
    """A few large differences are a step, not noise."""
    data = surface(roughness=1e-9)
    quiet = noise_level(data)
    data[:, SIZE // 2:] += 100e-9           # one big step
    assert noise_level(data) == pytest.approx(quiet, rel=0.25)
