"""
Finding the part of a frame that carries data.

Six of the thirty-one scans in the test pool stop partway, between 27% and 89%
of the frame empty. The first detector written for this found three of them,
and the three it missed were the three worst -- see test_median_trap below.
"""

import numpy as np
import pytest

from afm_copilot.frame import crop_to_data, dead_fraction, inspect, live_rows
from afm_copilot.gwy_io import Channel


def scan(rows=256, cols=256, dead_rows=0, dead_at="top", seed=1):
    """A scan with a constant band where the tip stopped."""
    data = np.random.default_rng(seed).normal(0, 1e-9, (rows, cols))
    if dead_rows:
        if dead_at == "top":
            data[rows - dead_rows:, :] = data[rows - dead_rows - 1, 0]
        else:
            data[:dead_rows, :] = data[dead_rows, 0]
    return Channel(name="Height", data=data, xreal=10e-6, yreal=10e-6)


def test_a_complete_scan_is_left_alone():
    channel = scan()
    cropped, report = crop_to_data(channel)
    assert not report["interrupted"]
    assert cropped is channel


@pytest.mark.parametrize("dead", [64, 128, 200])
@pytest.mark.parametrize("where", ["top", "bottom"])
def test_dead_band_is_found_at_either_end(dead, where):
    channel = scan(dead_rows=dead, dead_at=where)
    assert dead_fraction(channel.data) == pytest.approx(dead / 256, abs=0.02)


def test_median_trap():
    """
    The bug this module exists to avoid.

    With more than half the frame dead, the median row spread is itself zero.
    A test that compares against the median then compares against nothing and
    reports the whole frame as live. The three scans it missed in the pool were
    89%, 68% and 56% empty -- exactly the ones past the halfway mark.
    """
    channel = scan(dead_rows=228)          # 89% of the frame
    assert dead_fraction(channel.data) > 0.8


def test_cropping_corrects_the_physical_height():
    """
    Keeping the original height over fewer rows would stretch every distance
    measured afterwards by the ratio of the two.
    """
    channel = scan(dead_rows=64)           # a quarter of the frame
    cropped, report = crop_to_data(channel)
    assert cropped.yres == report["rows_kept"]
    assert cropped.yreal == pytest.approx(channel.yreal * 0.75, rel=0.02)
    # The pixel size along y must come out unchanged.
    assert (cropped.yreal / cropped.yres) == pytest.approx(
        channel.yreal / channel.yres, rel=0.02)


def test_x_is_untouched():
    channel = scan(dead_rows=64)
    cropped, _ = crop_to_data(channel)
    assert cropped.xreal == channel.xreal
    assert cropped.xres == channel.xres


def test_too_little_left_is_flagged_not_hidden():
    """
    The user cropped scans at 68% and 56% empty and discarded one at 89%.
    So the judgement is reported and the caller decides; nothing is dropped
    silently.
    """
    assert inspect(scan(dead_rows=228))["worth_keeping"] is False   # 11% left
    assert inspect(scan(dead_rows=174))["worth_keeping"] is True    # 32% left
    assert inspect(scan(dead_rows=80))["worth_keeping"] is True


def test_a_stray_live_row_does_not_keep_the_dead_band():
    channel = scan(dead_rows=100, dead_at="bottom")
    channel.data[20, :] = np.random.default_rng(7).normal(0, 1e-9, 256)
    top, _ = live_rows(channel.data)
    assert top >= 99
