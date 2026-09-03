"""
Is this scan worth using?

The tool has to do what a competent operator does at the microscope: glance at
an image and decide whether to keep it, fix it, or take it again. Not whether
it is perfect -- whether it is usable.

Every check here answers one question, returns a number, and says what it found
in a sentence. Nothing is discarded silently and nothing is discarded without a
reason a person can disagree with, because the cost of throwing away a good
scan is higher than the cost of keeping a mediocre one.

What is deliberately not here: judgements that need information we do not yet
have. Trace-and-retrace disagreement needs both channels. Mains interference
needs the scan speed, which conversion currently discards. Those arrive later.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from afm_copilot import frame
from afm_copilot.gwy_io import Channel

# Noise this close to the whole height variation means the image is mostly
# noise: there is no surface left to measure under it.
NOISE_DOMINATES = 0.55
NOISE_HEAVY = 0.30

# Row offsets this large relative to the surface itself. Below the first the
# lines are fine; between them they need aligning; above the second the offsets
# are the image.
BANDING_NEEDS_WORK = 0.08
BANDING_SEVERE = 0.60

# Rows that disagree with both neighbours far more than rows normally do.
GLITCH_ROWS_NOTABLE = 0.01
GLITCH_ROWS_SEVERE = 0.20

# Pixels sitting exactly at the top or bottom of the range: the instrument ran
# out of z and stopped following the surface.
SATURATION_NOTABLE = 0.005
SATURATION_SEVERE = 0.05

# Asymmetry of the slope along the fast axis, over and above the slow axis.
# The feedback lags, so features rise sharply and relax slowly -- and that
# lopsidedness appears on the time axis only.
FEEDBACK_LAG_NOTABLE = 0.8
FEEDBACK_LAG_SEVERE = 3.0


@dataclass
class Check:
    """One question asked of the scan."""

    name: str
    value: float
    verdict: str            # "ok" | "fixable" | "bad"
    says: str

    @property
    def is_bad(self) -> bool:
        return self.verdict == "bad"


@dataclass
class Quality:
    """What the checks add up to."""

    verdict: str            # "good" | "fixable" | "discard"
    checks: list[Check] = field(default_factory=list)

    @property
    def problems(self) -> list[Check]:
        return [c for c in self.checks if c.verdict != "ok"]

    def explain(self) -> str:
        head = {
            "good": "Usable as it is.",
            "fixable": "Usable once corrected.",
            "discard": "Not worth using.",
        }[self.verdict]
        lines = [head]
        for c in self.problems:
            lines.append(f"  - {c.says}")
        if not self.problems:
            lines.append("  - nothing wrong found")
        return "\n".join(lines)


def noise_level(data: np.ndarray) -> float:
    """
    Height noise, from the difference between neighbouring pixels in a row.

    Neighbouring pixels of a real surface are nearly the same height, so what
    separates them is mostly noise. The median absolute deviation is used
    rather than a standard deviation so that genuine steps -- a few large
    differences -- do not count as noise.
    """
    d = np.diff(np.asarray(data, dtype=float), axis=1)
    d = d[np.isfinite(d)]
    if d.size == 0:
        return 0.0
    mad = float(np.median(np.abs(d - np.median(d))))
    return 1.4826 * mad / math.sqrt(2.0)


def _check_noise(flat: np.ndarray) -> Check:
    spread = float(np.nanstd(flat))
    noise = noise_level(flat)
    ratio = noise / spread if spread > 0 else 0.0
    if ratio >= NOISE_DOMINATES:
        return Check("noise", ratio, "bad",
                     f"noise is {ratio:.0%} of the height variation -- there is "
                     "little surface left under it")
    if ratio >= NOISE_HEAVY:
        return Check("noise", ratio, "fixable",
                     f"noisy: {ratio:.0%} of the height variation is noise, "
                     "worth filtering before measuring")
    return Check("noise", ratio, "ok", f"noise is {ratio:.0%} of the variation")


def _check_banding(flat: np.ndarray) -> Check:
    """Offsets between scan lines, measured against the surface itself."""
    rows = np.nanmedian(flat, axis=1)
    if rows.size < 4:
        return Check("banding", 0.0, "ok", "too few rows to judge")
    offsets = float(np.nanstd(np.diff(rows)))
    spread = float(np.nanstd(flat))
    ratio = offsets / spread if spread > 0 else 0.0
    if ratio >= BANDING_SEVERE:
        return Check("banding", ratio, "bad",
                     f"the scan lines are offset from each other by more than "
                     f"the surface varies ({ratio:.0%}) -- the stripes are the "
                     "image")
    if ratio >= BANDING_NEEDS_WORK:
        return Check("banding", ratio, "fixable",
                     f"scan lines are offset from each other ({ratio:.0%} of "
                     "the surface variation) -- align the rows first")
    return Check("banding", ratio, "ok", f"scan lines sit level ({ratio:.0%})")


def _check_glitches(flat: np.ndarray) -> Check:
    """Single rows that disagree with both their neighbours."""
    rows = np.nanmedian(flat, axis=1)
    if rows.size < 5:
        return Check("glitches", 0.0, "ok", "too few rows to judge")
    neighbours = (np.roll(rows, 1) + np.roll(rows, -1)) / 2.0
    odd = np.abs(rows - neighbours)[1:-1]
    typical = float(np.median(odd))
    scatter = float(np.median(np.abs(odd - typical))) * 1.4826
    if scatter <= 0:
        return Check("glitches", 0.0, "ok", "no rows out of line")
    fraction = float(np.mean(odd > typical + 6.0 * scatter))
    if fraction >= GLITCH_ROWS_SEVERE:
        return Check("glitches", fraction, "bad",
                     f"{fraction:.0%} of the scan lines jump away from their "
                     "neighbours -- the tip was not tracking")
    if fraction >= GLITCH_ROWS_NOTABLE:
        return Check("glitches", fraction, "fixable",
                     f"{fraction:.1%} of the scan lines are out of line and "
                     "should be replaced")
    return Check("glitches", fraction, "ok", "no scan lines out of line")


def _check_saturation(raw: np.ndarray) -> Check:
    """Pixels pinned at the extremes: the instrument ran out of z."""
    values = np.asarray(raw, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return Check("saturation", 1.0, "bad", "no data")
    lo, hi = finite.min(), finite.max()
    if hi <= lo:
        return Check("saturation", 1.0, "bad", "the whole frame is one value")
    # Exact ties only. Counting everything *near* the extremes condemned the
    # best samples in the set -- a DVD's pit floors and a lithographic
    # pattern's plateaux are flat by design, not because the scanner ran out
    # of travel. Real clipping writes the identical number over and over.
    fraction = float(np.mean((finite == lo) | (finite == hi)))
    if fraction >= SATURATION_SEVERE:
        return Check("saturation", fraction, "bad",
                     f"{fraction:.0%} of the frame is pinned at the top or "
                     "bottom of the range -- the scanner ran out of travel")
    if fraction >= SATURATION_NOTABLE:
        return Check("saturation", fraction, "fixable",
                     f"{fraction:.1%} of the frame is pinned at the limits of "
                     "the range")
    return Check("saturation", fraction, "ok", "nothing clipped")


def _check_feedback(flat: np.ndarray) -> Check:
    """
    Does the height change lopsidedly along the fast axis?

    The feedback loop needs time to respond, so features rise sharply and
    relax slowly -- a lopsidedness that exists on the time axis and has no
    reason to exist across it. Comparing the two directions is what separates
    a lagging loop from a genuinely one-sided surface, which would be lopsided
    both ways.
    """
    dx = np.diff(flat, axis=1)
    dy = np.diff(flat, axis=0)
    dx, dy = dx[np.isfinite(dx)], dy[np.isfinite(dy)]
    if dx.size < 64 or dy.size < 64:
        return Check("feedback", 0.0, "ok", "too small to judge")

    def lopsidedness(d: np.ndarray) -> float:
        spread = float(np.std(d))
        if spread <= 0:
            return 0.0
        return abs(float(np.mean(((d - d.mean()) / spread) ** 3)))

    excess = lopsidedness(dx) - lopsidedness(dy)
    if excess >= FEEDBACK_LAG_SEVERE:
        return Check("feedback", excess, "bad",
                     "the surface rises and falls lopsidedly along the scan "
                     "direction only -- the tip was flying, not following")
    if excess >= FEEDBACK_LAG_NOTABLE:
        return Check("feedback", excess, "fixable",
                     "signs of the feedback lagging along the scan direction; "
                     "shapes will be smeared in that direction")
    return Check("feedback", excess, "ok", "the feedback kept up")


def assess(channel: Channel, acquisition=None) -> Quality:
    """
    Look at one scan and say whether to keep it, fix it, or drop it.

    The background comes out first: almost every check is about the surface,
    and a tilt would otherwise dominate all of them.

    `acquisition` is the instrument's own note, when the original file is at
    hand. It is optional and nothing depends on it -- it only adds what cannot
    be seen in the pixels.
    """
    from afm_copilot.decide import choose_background_degree
    from afm_copilot.features import subtract_background

    raw = np.asarray(channel.data, dtype=float)
    degree, _ = choose_background_degree(raw)
    flat = subtract_background(raw, max(1, degree))

    checks: list[Check] = []

    report = frame.inspect(channel)
    if report["interrupted"]:
        dead = report["dead_fraction"]
        if report["worth_keeping"]:
            checks.append(Check(
                "interrupted", dead, "fixable",
                f"the scan stopped early -- {dead:.0%} of the frame carries no "
                "data and will be cropped away"))
        else:
            checks.append(Check(
                "interrupted", dead, "bad",
                f"the scan stopped almost immediately -- {dead:.0%} of the "
                "frame is empty, too little left to measure"))
    else:
        checks.append(Check("interrupted", 0.0, "ok", "the scan completed"))

    checks.append(_check_saturation(raw))
    checks.append(_check_noise(flat))
    checks.append(_check_banding(flat))
    checks.append(_check_glitches(flat))
    checks.append(_check_feedback(flat))

    # The one thing the pixels cannot tell us: that somebody changed the
    # settings part-way down the frame. The instrument writes it into the note
    # -- "0.40064@Line: 229" -- and it explains images whose character changes
    # half way through, which otherwise look like a puzzling sample.
    line = getattr(acquisition, "changed_at_line", None)
    if line:
        total = channel.yres or 1
        where = line / total
        # Only when it happened in the body of the frame. Several real scans
        # record a change at line 509 of 512 -- the operator adjusting
        # something as the scan ended -- and that leaves nothing behind.
        if 0.05 < where < 0.95:
            checks.append(Check(
                "settings changed", where, "fixable",
                f"the scan settings were changed at line {line} of {total} -- "
                "the two parts were not taken under the same conditions"))

    # Discarding is the expensive mistake, so it takes more than one opinion.
    #
    # Two exceptions, both cases where there is simply nothing to work with: a
    # frame that never filled, and an image that is mostly noise. Otherwise a
    # single bad check is not enough -- every one of these measures misfires on
    # some legitimate surface, and the first calibration threw away 19% of the
    # set including the DVD that had just measured the scanner correctly.
    # Independent checks agreeing is far stronger evidence than any one of them
    # shouting, and a human operator discards a few scans in a batch, not a
    # fifth of it.
    fatal = [c for c in checks
             if c.is_bad and c.name in ("interrupted", "noise")]
    bad = [c for c in checks if c.is_bad]

    if fatal or len(bad) >= 2:
        verdict = "discard"
    elif bad or any(c.verdict == "fixable" for c in checks):
        verdict = "fixable"
    else:
        verdict = "good"
    return Quality(verdict=verdict, checks=checks)
