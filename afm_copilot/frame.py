"""
The part of the frame that actually carries data.

A scan that stopped early leaves the rest of the frame at one constant value.
That band is not a flat sample: it has no roughness, no periodicity and no
objects, so it drags every measurement toward "smooth" in proportion to how
early the scan stopped. Six of the thirty-one scans in the test pool are like
this, between 27% and 89% of the frame empty.

The instruction is to crop and carry on, not to discard -- the part that was
measured is good data. But there is a floor: the user kept scans at 68% and
56% empty because what survived still carried a measurable step, and discarded
one at 89% because it did not. So cropping is offered with the numbers, and a
scan that has too little left is flagged rather than silently processed.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from afm_copilot.gwy_io import Channel

# A row counts as dead when its height variation has collapsed to essentially
# nothing next to a live row.
DEAD_ROW_FRACTION = 0.02

# And never above this much of the image's own noise: a row quieter than the
# noise is not measuring anything, and a row noisier than it is.
DEAD_ROW_NOISE = 0.5

# Below this much of the frame surviving, what is left is not worth measuring.
# Calibrated against the user's own calls on the six interrupted scans in the
# pool: they kept one with 32% of the frame surviving -- because what remained
# still carried a film-thickness step -- and discarded one with 11%. The
# boundary lies between those two, and this sits in the middle of the gap
# rather than at either edge.
MIN_SURVIVING = 0.20

# Dead rows inside the measured region up to this many in a row are bridged
# rather than treated as the end of the data: a few saturated or flat lines in
# the middle of good data are a glitch, not where the scan stopped.
MAX_INTERIOR_GAP = 4


def live_rows(data: np.ndarray) -> tuple[int, int]:
    """
    First and last row that carry data, inclusive.

    The reference for "a live row" is the ninetieth percentile of the row
    spreads, deliberately **not** the median. With more than half the frame
    dead the median spread is itself zero, the test compares against nothing
    and reports the whole frame as live -- which is exactly how the first
    version of this found three of the six interrupted scans and missed the
    three worst ones.
    """
    values = np.asarray(data, dtype=float)
    spread = np.nan_to_num(np.nanstd(values, axis=1))
    n = spread.size
    if n == 0:
        return 0, 0

    typical = float(np.percentile(spread, 90))
    if typical <= 0:
        return 0, n - 1

    # A dead row is *constant*; a flat row still has noise. Judging deadness as
    # a fraction of the busiest rows made the threshold depend on whatever else
    # is in the frame: on a scan with one tall object it came to 3.5 nm while
    # the image's own noise was 1.1, so ordinary substrate rows were called
    # dead and 8% of the frame was thrown away. One scan lost 28% that way.
    from afm_copilot.quality import noise_level

    floor = DEAD_ROW_FRACTION * typical
    noise = noise_level(values)
    if noise > 0:
        floor = min(floor, DEAD_ROW_NOISE * noise)

    live = spread > floor
    if not live.any():
        return 0, n - 1

    # Take the longest unbroken stretch of live rows, not the outermost ones.
    # Trimming from the ends looks equivalent and is not: a single row that
    # happens to look live -- the half-written line where the scan stopped, a
    # spike -- halts the trim and keeps the whole dead band with it.
    #
    # Small gaps inside the stretch are bridged first, so a few saturated or
    # flat rows in the middle of good data do not split it in two.
    bridged = live.copy()
    gap = 0
    for i in range(n):
        if live[i]:
            if 0 < gap <= MAX_INTERIOR_GAP:
                bridged[i - gap:i] = True
            gap = 0
        else:
            gap += 1

    best_start, best_length = 0, 0
    start = None
    for i in range(n + 1):
        if i < n and bridged[i]:
            if start is None:
                start = i
        elif start is not None:
            if i - start > best_length:
                best_start, best_length = start, i - start
            start = None

    if best_length == 0:
        return 0, n - 1
    return best_start, best_start + best_length - 1


def dead_fraction(data: np.ndarray) -> float:
    """How much of the frame carries no data, as a fraction of the rows."""
    n = np.asarray(data).shape[0]
    if n == 0:
        return 0.0
    top, bottom = live_rows(data)
    return float(n - (bottom - top + 1)) / float(n)


def inspect(channel: Channel) -> dict:
    """
    Report on the frame without changing anything.

    Returns the dead fraction, the rows that survive, and whether cropping
    leaves enough to be worth measuring. The judgement is reported, never
    acted on silently -- whether what remains is useful depends on what is in
    it, and that is the user's call.
    """
    data = np.asarray(channel.data, dtype=float)
    top, bottom = live_rows(data)
    kept = bottom - top + 1
    total = data.shape[0]
    dead = float(total - kept) / float(total) if total else 0.0
    return {
        "interrupted": dead > 0.02,
        "dead_fraction": dead,
        "first_row": top,
        "last_row": bottom,
        "rows_kept": kept,
        "rows_total": total,
        "worth_keeping": (kept / total) >= MIN_SURVIVING if total else False,
        "kept_height": channel.yreal * kept / total if total else 0.0,
    }


def crop_to_data(channel: Channel) -> tuple[Channel, dict]:
    """
    The same scan with the empty band removed and its size corrected.

    Recomputing the physical height is the part that must not be forgotten:
    keeping the original `yreal` over fewer rows would stretch every distance
    measured afterwards by the ratio of the two.
    """
    report = inspect(channel)
    if not report["interrupted"]:
        return channel, report

    top, bottom = report["first_row"], report["last_row"]
    data = np.asarray(channel.data)[top:bottom + 1, :]
    kept = report["rows_kept"]

    cropped = replace(
        channel,
        data=data,
        yreal=channel.yreal * kept / report["rows_total"],
        meta=dict(channel.meta,
                  cropped_from_rows=report["rows_total"],
                  cropped_rows=(top, bottom),
                  cropped_dead_fraction=report["dead_fraction"]),
    )
    return cropped, report
