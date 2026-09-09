"""
Measurements that turn an image into a number, with an honest error bar.

The flagship case is film thickness from a scratch: the scratch exposes the
substrate, the rest of the frame is intact film, so the height histogram has
two populations and the thickness is the distance between them.

The important design decision here is that a measurement can **refuse**. If the
histogram is not actually bimodal, there is no step to measure, and returning a
number anyway would be worse than useless -- it would be a plausible number.
Every result therefore carries a confidence and a list of warnings, and
`ok` is False when the data does not support the measurement.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from afm_copilot.gwy_io import Channel
from afm_copilot.profile import Profile

# Two independent tests decide whether a step is measurable, because neither
# works alone. The thresholds below were calibrated by measuring both
# quantities across known-good and known-bad cases, synthetic and real:
#
#   case                          separability   plane fraction
#   ---------------------------   ------------   --------------
#   Gaussian noise                    0.64            0.00
#   fractal surface                   0.59            0.00
#   unlevelled ramp                   0.75            1.00
#   unlevelled ramp + real step       0.82            0.95
#   real 20 nm step, 5 nm rough       0.79            0.48
#   real 5 nm step, 1 nm rough        0.84            0.53
#   real 40 nm step, 1 nm rough       1.00            0.62
#
# Note the overlap in the first column: an unlevelled ramp with a step scores
# 0.82, HIGHER than a genuine 20 nm step at 0.79. Separability alone would
# accept the un-measurable case and reject the measurable one. The plane
# fraction is what tells them apart, and there the gap is wide -- 0.95 versus
# 0.62.

# Below this, the height distribution is one population being cut in half
# rather than two levels.
MIN_SEPARABILITY = 0.75

# Above this, the two levels are clearly resolved. Between the two, the answer
# is reported but flagged as marginal rather than silently trusted.
CONFIDENT_SEPARABILITY = 0.85

# If a plane explains this much of the height variation, the image is still
# tilted or bowed. Any "step" found in it is the slope, not a step.
MAX_PLANE_FRACTION = 0.90

# Secondary check: how far apart the two medians are relative to their own
# scatter. Kept because it is easy to interpret, but note that splitting a
# Gaussian already yields ~2.2, so this alone can never detect bimodality.
MIN_SEPARATION_RATIO = 2.0

# A population holding less than this fraction of the frame is not a level.
#
# This was 2%, and the user's objection was exactly right: the histogram alone
# is not enough, the surface share has to be checked too. Sorted by the smaller
# of the two populations, the batch separates cleanly and by name -- and the
# names were never read by any of this:
#
#     2.3%   NPs coated SiO2 50 nm006          a field of particles
#     3.1%   NP on MICA 240228009006           a field of particles
#     7.3%   Nanoparticles 1                   365 of them
#     9.4%   150121Z Detector015               63 of them
#    18.5%   DVD240122003005                   pits in a disc
#     ---------------------------------------------------------
#    24.9%   SKPM_0013                         a flake on a substrate
#    32.1%   PEAPbBr002                        a perovskite film
#    37.1%   ALEX_AS_SGHS_Br_I0022             a real step
#    46.8%   Calibration grating - Vertical    a certified step
#
# Everything below the line is a minority of *objects* whose heights happen to
# split the histogram. Two true steps sit just under the bar and are lost with
# them (an electrode at 18.8%, an ITO feature at 14.3%). That is the direction
# to lose them in.
MIN_POPULATION_FRACTION = 0.20


@dataclass
class StepResult:
    """A measured step height, with everything needed to judge it."""

    ok: bool
    value: float = float("nan")          # metres
    uncertainty: float = float("nan")    # metres, 1 sigma
    lower_level: float = float("nan")
    upper_level: float = float("nan")
    lower_std: float = float("nan")
    upper_std: float = float("nan")
    lower_fraction: float = float("nan")
    upper_fraction: float = float("nan")
    separation_ratio: float = float("nan")
    separability: float = float("nan")     # Otsu eta, 0..1
    plane_fraction: float = float("nan")   # residual tilt, 0..1
    confidence: str = "rejected"           # "good" | "marginal" | "rejected"
    method: str = ""
    source: str = ""
    warnings: list[str] = field(default_factory=list)

    def explain(self) -> str:
        if not self.ok:
            lines = [f"No step measured in {self.source or 'this image'}."]
            lines.extend(f"  - {w}" for w in self.warnings)
            return "\n".join(lines)

        from afm_copilot.render import pick_unit
        factor, unit = pick_unit(abs(self.value))
        lines = [
            f"Step height: {self.value / factor:.3f} +/- "
            f"{self.uncertainty / factor:.3f} {unit}"
            + ("   [MARGINAL]" if self.confidence == "marginal" else ""),
            f"  Method: {self.method}",
            # For a manual measurement the fractions describe the points the
            # user selected, not the image -- saying "of the frame" there would
            # be wrong.
            (f"  Lower region has {self.lower_fraction * 100:.0f}% of the "
             f"selected points, upper region {self.upper_fraction * 100:.0f}%."
             if self.method.startswith("manual") else
             f"  Lower level covers {self.lower_fraction * 100:.0f}% of the "
             f"frame, upper level {self.upper_fraction * 100:.0f}%."),
            f"  The two levels are separated by "
            f"{self.separation_ratio:.1f}x their own scatter"
            f" -- {'clearly distinct' if self.separation_ratio > 4 else 'distinguishable but close'}.",
        ]
        lines.extend(f"  ! {w}" for w in self.warnings)
        return "\n".join(lines)


def _otsu_split(values: np.ndarray, bins: int = 256) -> tuple[float, float]:
    """
    Split a distribution into two classes by maximising between-class variance.

    Returns (threshold, separability), where separability is the fraction of
    the total variance the split explains -- Otsu's eta. That second number is
    what makes the refusal case work: Otsu always returns a threshold, even for
    a single smooth population, so the threshold alone proves nothing. Eta says
    whether the split describes real structure.
    """
    hist, edges = np.histogram(values, bins=bins)
    centres = (edges[:-1] + edges[1:]) / 2.0
    total = hist.sum()
    if total == 0:
        return float(np.median(values)), 0.0

    weight_bg = np.cumsum(hist).astype(float)
    weight_fg = total - weight_bg
    valid = (weight_bg > 0) & (weight_fg > 0)
    if not valid.any():
        return float(np.median(values)), 0.0

    cum_mean = np.cumsum(hist * centres)
    mean_total = cum_mean[-1] / total
    mean_bg = np.divide(cum_mean, weight_bg, out=np.zeros_like(cum_mean),
                        where=weight_bg > 0)
    mean_fg = np.divide(cum_mean[-1] - cum_mean, weight_fg,
                        out=np.zeros_like(cum_mean), where=weight_fg > 0)

    # Between-class variance, in the same units as the data's variance.
    between = (weight_bg / total) * (weight_fg / total) * (mean_bg - mean_fg) ** 2
    between[~valid] = -np.inf
    best = int(np.argmax(between))

    total_var = float(np.sum(hist * (centres - mean_total) ** 2) / total)
    eta = float(between[best] / total_var) if total_var > 0 else 0.0
    return float(centres[best]), max(0.0, min(1.0, eta))


# --------------------------------------------------------------------------
# which measurement a scan is actually for
# --------------------------------------------------------------------------

# Two clearly separated height levels: the mark of a step, a scratch or a
# terrace, and the condition for a thickness to mean anything.
TWO_LEVELS = 0.50

# Below this much of the frame departing from the surface, and with no step,
# a single roughness describes the scan.
UNIFORM_ENOUGH = 0.03

# Enough separate objects that their sizes say something.
ENOUGH_PARTICLES = 5

# A peak in the height histogram counts as a level when it reaches this much
# of the tallest peak and stands this far clear of the valleys beside it. Both
# are needed: a shoulder on one broad hump is tall but not prominent, and a
# ripple in the tail is prominent but not tall.
LEVEL_MIN_HEIGHT = 0.12
LEVEL_MIN_PROMINENCE = 0.10

# Between two real levels the histogram comes back down to this fraction of the
# smaller of them, and each level is no wider at half height than this fraction
# of the gap between them. Two populations that meet in a shallow dip, or that
# are as broad as they are far apart, are one population with a bump in it.
VALLEY_DROPS_TO = 0.55
PEAK_IS_NARROW = 0.75

# Objects this round are spheres rather than flakes or rods, and a field of
# them is a particle layer -- the user's rule, and the condition under which a
# size may be quoted without hedging.
ROUND_ENOUGH = 1.4

# This many separate pieces is a scattering, and a scattering has no step
# height however cleanly its heights split. Set above the handful of grains a
# real stepped surface can carry (a perovskite film shows 7, a flake 2) and
# below the fields that were being called steps (51 fibres, 63 particles).
MANY_SEPARATE_PIECES = 20

# The tip correction is worth quoting while it actually shrinks the object.
# Once the answer comes back at nearly the measured width the formula has left
# its range -- the object is far bigger than the probe and the tip adds a rim,
# not a factor -- and quoting two nearly equal numbers pretends to a precision
# that is not there.
TIP_CORRECTION_WORTH_IT = 0.90

# A roughness of the background needs a background to measure. Below this share
# of the frame the objects are the sample and what is left between them is not
# a surface, it is the gaps.
ENOUGH_BACKGROUND = 0.40


@dataclass
class Reading:
    """One measurement, with the reason it was the right one to take."""

    kind: str                        # thickness | roughness | particles
    headline: str
    detail: str = ""
    caveat: str = ""


FAMILIES: dict[str, str] = {
    "terraces": "terrazze e gradini",
    "particles": "strati di nanoparticelle",
    "objects": "oggetti su un fondo",
    "pattern": "reticoli e strutture periodiche",
    "pits": "cavita e fori",
    "uniform": "superfici uniformi",
    "other": "senza una famiglia decisa",
}


def family_of(readings: Sequence[Reading], measurements: dict) -> str:
    """
    Which pile a scan belongs on, so the like ones can be looked at together.

    Ordered by how decisive each signal is rather than by how interesting it
    is: a scan showing several of these lands in the pile whose evidence is
    hardest to argue with. Levels in the histogram come first -- they are a
    fact about the height distribution with no detector in between. A field of
    round objects, all much the same size, is next. A lattice that agrees with
    itself is third. Anything surviving none of those goes to 'other', which
    here is a real answer and not a failure.
    """
    kinds = {r.kind for r in readings}

    # Matched on how a headline starts, not on what it contains: a refusal
    # reads "no step here, though the heights look split", and a substring
    # test for "step" filed 58 of those under terraces.
    if any(r.headline.startswith(("step ", "terraces at"))
           for r in readings):
        return "terraces"
    # A lattice comes before a particle layer, not after. Round even objects
    # repeating at a fixed pitch are a made structure; the periodicity is the
    # harder evidence and it is what the scan is about.
    if "pattern" in kinds:
        return "pattern"
    if any(r.headline.startswith("nanoparticle layer") for r in readings):
        return "particles"
    if "particles" in kinds:
        polarity = measurements.get("object_polarity") or 0
        return "pits" if polarity < 0 else "objects"
    if "roughness" in kinds:
        return "uniform"
    return "other"


def height_levels(channel: Channel, max_levels: int = 4) -> list[float]:
    """
    The distinct heights a surface sits at, when there clearly are some.

    Terraces, a film beside its substrate, a patterned layer: the height
    histogram shows two or three sharp peaks and the spacing between them is
    the answer. The user's condition, and it is the right one -- *two or three
    well-defined Gaussian peaks* -- because a broad or single-humped histogram
    means one population, and quoting a step height for it is a number about
    nothing.

    Returns the peak positions in metres, or an empty list where the histogram
    does not clearly separate.
    """
    from scipy import ndimage, signal

    values = np.asarray(channel.data, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size < 1024:
        return []

    lo, hi = np.percentile(finite, (0.5, 99.5))
    if hi <= lo:
        return []
    counts, edges = np.histogram(finite, bins=256, range=(lo, hi))
    smooth = ndimage.gaussian_filter1d(counts.astype(float), 2.0)
    if smooth.max() <= 0:
        return []
    smooth /= smooth.max()

    found, _ = signal.find_peaks(
        smooth, height=LEVEL_MIN_HEIGHT, prominence=LEVEL_MIN_PROMINENCE,
        distance=len(smooth) // 20)
    if not (2 <= len(found) <= max_levels):
        return []
    found = np.sort(found)

    # Now the part that decides. On this batch the two tests above alone put
    # 105 of 199 scans in the terrace pile, which is nonsense -- a shoulder or
    # a ripple on one broad hump clears both. What separates real levels from
    # one population is the shape between and around the peaks:
    #
    #   the valley between two levels comes back down       (VALLEY_DROPS_TO)
    #   each level is narrow next to the gap beside it      (PEAK_IS_NARROW)
    #
    # Those are what "molto definiti" means when written down.
    widths, _, _, _ = signal.peak_widths(smooth, found, rel_height=0.5)
    for left, right, w_left, w_right in zip(found[:-1], found[1:],
                                            widths[:-1], widths[1:]):
        valley = float(smooth[left:right + 1].min())
        if valley > VALLEY_DROPS_TO * min(smooth[left], smooth[right]):
            return []
        if max(w_left, w_right) > PEAK_IS_NARROW * (right - left):
            return []

    centres = (edges[:-1] + edges[1:]) / 2.0
    return [float(centres[i]) for i in found]


def background_roughness(channel: Channel) -> tuple[float, float] | None:
    """
    How smooth the surface is where nothing is sitting on it.

    Returns the Sq of the unmasked region and the share of the frame that was
    masked out, or None where too little background survives to measure.

    The mask is the same one the levelling uses, grown a little further: the
    skirt around an object is the tip's own shape smeared out, and counting it
    as surface would inflate exactly the number this is meant to protect.
    """
    from scipy import ndimage

    from afm_copilot.decide import level, object_mask

    values = np.asarray(channel.data, dtype=float)
    if values.ndim != 2 or values.size < 1024:
        return None

    settled = level(values)
    mask = object_mask(settled.flat)
    if mask.any():
        mask = ndimage.binary_dilation(mask, iterations=2)

    background = np.asarray(settled.flat)[~mask & np.isfinite(settled.flat)]
    if background.size < ENOUGH_BACKGROUND * values.size:
        return None
    return float(np.std(background)), float(mask.mean())


def readings_for(channel: Channel, measurements: dict,
                 tip_radius: float | None = None) -> list[Reading]:
    """
    Decide what a scan is *for*, then take that measurement.

    A batch is not a uniform thing to be measured uniformly. One scan carries a
    step and its answer is a thickness; the next is a flat film and its answer
    is a roughness; a third is covered in particles and its answer is how many
    and how big. Measuring all three the same way yields three numbers, two of
    which describe nothing.

    Where none of the three applies, the honest output is none of them.
    """
    from afm_copilot.tip import feature_radius

    out: list[Reading] = []
    bimodality = float(measurements.get("bimodality", 0.0) or 0.0)
    objects = float(measurements.get("object_fraction", 0.0) or 0.0)
    count = int(measurements.get("object_count", 0) or 0)
    polarity = int(measurements.get("object_polarity", 0) or 0)
    rms = float(measurements.get("rms", 0.0) or 0.0)
    correlation = measurements.get("correlation_length")

    # Three or more sharp peaks is a staircase, and the film-thickness routine
    # -- which is built around exactly two populations -- has nothing to say
    # about it. The peak spacings are the terrace heights and are reported
    # directly. Two peaks go the usual route, which carries an error bar.
    # A minority population made of dozens of separate pieces is a scattering
    # of objects, not a level, whatever share of the frame it holds. That is
    # what put a fibre network among the steps at 30% -- above the surface-share
    # bar, and still 51 separate strands.
    scattered = count >= MANY_SEPARATE_PIECES

    levels = height_levels(channel)
    if scattered and len(levels) < 3:
        levels = []
    if len(levels) >= 3:
        gaps = np.diff(levels)
        out.append(Reading(
            "thickness",
            "terraces at " + ", ".join(f"{g * 1e9:.1f}" for g in gaps) + " nm",
            f"the height histogram has {len(levels)} sharp peaks, so the "
            "surface sits at that many definite levels",
            "A height is the one thing neither the tip nor the scanner "
            "distorts, so these are the most trustworthy numbers here."))
    elif (len(levels) == 2 or bimodality >= TWO_LEVELS) and not scattered:
        try:
            step = measure_film_thickness(channel)
        except Exception as exc:                               # noqa: BLE001
            step = None
            refusal = str(exc)[:150]
        else:
            refusal = "; ".join(step.warnings or []) if not step.ok else ""

        # A measurement that refuses has to be reported as a refusal. This
        # module is built so that it *can* refuse -- returning a plausible
        # number where there is no step is the failure it exists to avoid --
        # and reading past `ok` printed "step nan nm" on three scans, which is
        # worse than either the number or the refusal alone.
        if step is not None and step.ok:
            out.append(Reading(
                "thickness", f"step {step.value * 1e9:.1f} nm",
                f"+/- {step.uncertainty * 1e9:.1f} nm, from the two levels the "
                f"heights fall into (separability {bimodality:.2f})",
                "A height is the one thing neither the tip nor the scanner "
                "distorts, so this is the most trustworthy number here."))
        else:
            # There was a branch here that quoted the peak spacing when the
            # routine above declined. It was wrong, and on a scan of crossing
            # fibres it printed "step 35.1 nm" directly underneath that
            # routine's own words: "this is one population, not two ... there
            # is no measurable step in this image". A refusal is a result. It
            # does not get a second opinion from a weaker test.
            out.append(Reading(
                "thickness", "no step here, though the heights look split",
                refusal or "the two levels are not separated enough to measure",
                "Reported rather than a number: a plausible thickness where "
                "there is no step is the one output worth nothing at all."))

    confirmed = float(measurements.get("period_confirmed", 0.0) or 0.0)
    spacing = measurements.get("period_length")
    if confirmed > 0 and spacing and np.isfinite(spacing):
        angle = measurements.get("period_angle")
        # How convincingly it repeats, out of a possible 2, separates a
        # manufactured pattern from a surface that merely has a preferred
        # spacing: a calibration grating scores about 1.9, a grain structure
        # between 0.5 and 0.7.
        made = ("regular enough to be manufactured" if confirmed > 1.4
                else "a preferred spacing rather than a made pattern")
        out.append(Reading(
            "pattern", f"pitch {spacing * 1e9:.0f} nm",
            (f"repeating at {angle:.0f}°" if angle is not None
             and np.isfinite(angle) else "repeating")
            + f", {made} (agreement {confirmed:.2f} of 2)",
            "The spacing is a lateral distance, so it carries the scanner's "
            "calibration with it -- two scans of one DVD in this set disagree "
            "by 12 to 16%."))

    # A substrate with three specks on it fell between every rule: too busy
    # for the whole-frame roughness (which needs under 3% of the frame in
    # objects), too empty to count them (which needs five). Twenty-four scans
    # of this batch sat in that gap, and the gap was an accident -- two
    # thresholds chosen for unrelated reasons that were never checked against
    # each other.
    #
    # The answer is not to widen either bar but to measure the thing the
    # operator actually wants to know about such a scan: how smooth the
    # background is. The objects are excluded rather than tolerated, using the
    # same mask that keeps them out of the levelling.
    # The test is "no step was reported", not "the heights did not look
    # split". Ten of these scans have a split-looking histogram and a step
    # routine that examined it and refused -- and a refusal there says *one
    # population*, which is exactly the case where the roughness of that one
    # population is the right answer. Reading the raw bimodality instead left
    # them with nothing at all.
    stepped = any(r.kind == "thickness" and not r.headline.startswith("no step")
                  for r in out)
    if UNIFORM_ENOUGH <= objects and count < ENOUGH_PARTICLES and not stepped:
        clean = background_roughness(channel)
        if clean is not None:
            sq, share = clean
            out.append(Reading(
                "roughness", f"Sq {sq * 1e9:.2f} nm",
                f"of the background alone, with {share:.0%} of the frame "
                f"masked out -- {count} object"
                f"{'s' if count != 1 else ''} on an otherwise even surface",
                "Excluding the objects rather than tolerating them: over the "
                f"whole frame this reads {rms * 1e9:.2f} nm, which is mostly "
                "their height and says little about the surface."))

    if objects < UNIFORM_ENOUGH and bimodality < TWO_LEVELS:
        detail = "over the whole frame"
        if correlation and np.isfinite(correlation):
            detail += (f"; the surface stops resembling itself after "
                       f"{correlation * 1e9:.0f} nm, which is the length a "
                       "cut-off should respect")
        out.append(Reading(
            "roughness", f"Sq {rms * 1e9:.2f} nm", detail,
            "Levelling always takes some real roughness with the artifact, so "
            "this is a lower bound -- row-by-row correction costs far more "
            "than whole-image levelling."))

    if count >= ENOUGH_PARTICLES and polarity != 0:
        median = float(measurements.get("object_median_size", 0.0) or 0.0)
        spread = float(measurements.get("object_size_spread", 0.0) or 0.0)
        elongation = float(measurements.get("object_elongation", 0.0) or 0.0)
        what = "pits" if polarity < 0 else "particles"

        detail_parts = [f"{count} of them"]
        if spread:
            detail_parts.append(
                ("all much the same size" if spread < 0.35
                 else "a wide range of sizes") + f" (spread {spread:.0%})")
        if elongation >= 1.6:
            detail_parts.append(f"elongated, about {elongation:.1f} to 1")

        # Named only when the attribution is not in doubt: enough of them,
        # round rather than elongated, all much the same size. That is a layer
        # of particles and may be called one; anything else keeps the neutral
        # word.
        #
        # Not where the objects sit on a lattice, though. Deposited particles
        # do not arrange themselves at a regular 830 nm pitch; something that
        # does is a manufactured structure, and two scans of a DVD were being
        # called a nanoparticle layer on the strength of round, even bumps.
        periodic = any(r.kind == "pattern" for r in out)
        if (polarity > 0 and count >= ENOUGH_PARTICLES and not periodic
                and 0 < elongation <= ROUND_ENOUGH and spread < 0.35):
            what = "nanoparticle layer"

        headline = f"{what}, {median * 1e9:.0f} nm across"
        caveat = ""
        if tip_radius and median > 0:
            true_across = 2.0 * feature_radius(median, tip_radius)
            if median <= 2.0 * tip_radius:
                # Smaller than the probe: what was measured is the tip's own
                # shape with the object somewhere inside it. The formula still
                # returns a number -- 1 nm from a 7 nm measurement -- and it is
                # a number about the tip.
                caveat = (f"As measured. These are no larger than the "
                          f"{tip_radius * 1e9:.0f} nm probe, so the width is "
                          "mostly the tip's own shape and there is no object "
                          "size to recover from it.")
            elif true_across >= median * TIP_CORRECTION_WORTH_IT:
                # The correction has run out of range -- these objects are far
                # larger than the probe, and what the tip adds to their width
                # is a rim, not a doubling. Reported as measured, and said so.
                caveat = (f"As measured. These are much larger than the "
                          f"{tip_radius * 1e9:.0f} nm probe, so the tip adds a "
                          "rim rather than a factor, and the correction that "
                          "suits small particles does not apply.")
            else:
                headline = (f"{what}, {true_across * 1e9:.0f} nm across "
                            f"({median * 1e9:.0f} nm as measured)")
                caveat = (f"The measured width includes the tip; corrected for "
                          f"a {tip_radius * 1e9:.0f} nm probe. A blunter probe "
                          "would mean smaller objects still.")
        out.append(Reading("particles", headline, ", ".join(detail_parts),
                           caveat))

    return out


def plane_fraction(data: np.ndarray) -> float:
    """
    Fraction of the height variance a best-fit plane accounts for.

    This is the residual-tilt detector. On a properly levelled image it stays
    well below 1 even when a step edge gives the plane something to lean on;
    on an image that still has tilt or bow it approaches 1, and any "step"
    found in the histogram is really the slope.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        return 0.0
    finite = np.isfinite(data)
    if finite.sum() < 16:
        return 0.0

    h, w = data.shape
    y, x = np.mgrid[0:h, 0:w]
    design = np.column_stack([x[finite].ravel(), y[finite].ravel(),
                              np.ones(finite.sum())])
    z = data[finite].ravel()
    total_var = float(np.var(z))
    if total_var <= 0:
        return 0.0
    try:
        coef, *_ = np.linalg.lstsq(design, z, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    return float(np.var(design @ coef) / total_var)


def measure_step(
    heights: np.ndarray,
    source: str = "",
    method_label: str = "two-level histogram split (Otsu)",
) -> StepResult:
    """
    Measure the distance between two height populations.

    Uses medians rather than means for each level, so a few spikes or a bit of
    residual scar do not move the answer.

    Pass the full 2D array where possible: the residual-tilt check needs the
    spatial layout, and it is the test that catches an unlevelled image.
    """
    raw = np.asarray(heights, dtype=float)
    values = raw.ravel()
    values = values[np.isfinite(values)]
    result = StepResult(ok=False, method=method_label, source=source)

    if values.size < 100:
        result.warnings.append("too few valid data points to measure anything")
        return result

    if raw.ndim == 2:
        result.plane_fraction = plane_fraction(raw)
        if result.plane_fraction >= MAX_PLANE_FRACTION:
            result.warnings.append(
                f"this image is still tilted or bowed: a single plane accounts "
                f"for {result.plane_fraction * 100:.0f}% of the height "
                f"variation. Any step found here would be the slope, not a "
                f"step. Level it first -- try the 'clean-with-features' recipe.")
            return result

    threshold, separability = _otsu_split(values)
    result.separability = separability
    lower = values[values <= threshold]
    upper = values[values > threshold]

    if lower.size == 0 or upper.size == 0:
        result.warnings.append("the data does not split into two levels at all")
        return result

    if separability < MIN_SEPARABILITY:
        result.warnings.append(
            f"this is one population, not two: the best possible split "
            f"explains only {separability * 100:.0f}% of the height variation, "
            f"and a real step reaches at least {MIN_SEPARABILITY * 100:.0f}%. "
            f"There is no measurable step in this image.")
        return result

    result.confidence = ("good" if separability >= CONFIDENT_SEPARABILITY
                         else "marginal")
    if result.confidence == "marginal":
        result.warnings.append(
            f"marginal: the split explains {separability * 100:.0f}% of the "
            f"height variation, below the {CONFIDENT_SEPARABILITY * 100:.0f}% "
            f"that marks a cleanly resolved step. The value is usable as an "
            f"estimate, but the surfaces are rough compared with the step.")

    result.lower_level = float(np.median(lower))
    result.upper_level = float(np.median(upper))
    result.lower_std = float(np.std(lower))
    result.upper_std = float(np.std(upper))
    result.lower_fraction = lower.size / values.size
    result.upper_fraction = upper.size / values.size

    step = result.upper_level - result.lower_level
    pooled = float(np.hypot(result.lower_std, result.upper_std)) / np.sqrt(2)
    result.value = step
    # The step is a difference of two medians, so the uncertainties add in
    # quadrature; the standard error of a median is ~1.25x that of a mean.
    result.uncertainty = float(np.hypot(
        1.253 * result.lower_std / np.sqrt(max(1, lower.size)),
        1.253 * result.upper_std / np.sqrt(max(1, upper.size))))
    result.separation_ratio = float(step / pooled) if pooled > 0 else float("inf")

    if result.separation_ratio < MIN_SEPARATION_RATIO:
        result.warnings.append(
            f"the two levels overlap too much to be called a step "
            f"(separation {result.separation_ratio:.1f}x their scatter, "
            f"need at least {MIN_SEPARATION_RATIO}). This image probably has "
            f"no clean step -- or it needs flattening first.")
        return result

    if min(result.lower_fraction, result.upper_fraction) < MIN_POPULATION_FRACTION:
        result.warnings.append(
            f"one level covers only "
            f"{min(result.lower_fraction, result.upper_fraction) * 100:.1f}% "
            f"of the frame, which is too little to characterise reliably. "
            f"The value is reported but treat it as indicative.")

    # A real film step should be far larger than the roughness of either level.
    if result.lower_std > abs(step) / 3 or result.upper_std > abs(step) / 3:
        result.warnings.append(
            "one of the levels is rougher than a third of the step height, so "
            "the surfaces are not flat compared with what is being measured.")

    result.ok = True
    return result


def measure_film_thickness(channel: Channel) -> StepResult:
    """
    Film thickness from a scratch image.

    Assumes the frame contains both exposed substrate and intact film. The
    channel must be levelled first -- an unflattened tilt spreads both
    populations until they merge, which the separation test will then reject.
    """
    result = measure_step(
        channel.data,
        source=str(channel.source.name if channel.source else channel.name),
        method_label="film thickness: two-level histogram split of the frame",
    )
    if result.ok and result.value <= 0:
        result.warnings.append(
            "the upper level sits below the lower one, which should be "
            "impossible for a film on a substrate -- check the channel sign.")
    return result


def measure_step_iso5436(profile: Profile, source: str = "") -> StepResult:
    """
    Step height from a profile using the ISO 5436 convention.

    The standard deliberately averages over the middle third of each plateau
    and ignores the edge zones, because feedback overshoot and tip rounding
    corrupt exactly the region next to the edge.
    """
    z = np.asarray(profile.height, dtype=float)
    z = z[np.isfinite(z)]
    result = StepResult(ok=False, method="ISO 5436 middle-third plateaux",
                        source=source)
    if z.size < 30:
        result.warnings.append("profile too short for the ISO 5436 procedure")
        return result

    threshold, separability = _otsu_split(z)
    result.separability = separability
    if separability < MIN_SEPARABILITY:
        result.warnings.append(
            f"this profile crosses one level, not two: the best split explains "
            f"only {separability * 100:.0f}% of the height variation")
        return result
    is_upper = z > threshold

    # Take the longest contiguous run on each level as the plateau, then use
    # only its middle third -- that is the part the standard trusts.
    def middle_third(mask: np.ndarray) -> np.ndarray:
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            return np.array([])
        splits = np.split(idx, np.flatnonzero(np.diff(idx) != 1) + 1)
        run = max(splits, key=len)
        if run.size < 3:
            return z[run]
        third = run.size // 3
        return z[run[third: run.size - third]]

    upper_vals = middle_third(is_upper)
    lower_vals = middle_third(~is_upper)
    if upper_vals.size == 0 or lower_vals.size == 0:
        result.warnings.append("could not find two plateaux in this profile")
        return result

    result.lower_level = float(np.mean(lower_vals))
    result.upper_level = float(np.mean(upper_vals))
    result.lower_std = float(np.std(lower_vals))
    result.upper_std = float(np.std(upper_vals))
    result.lower_fraction = lower_vals.size / z.size
    result.upper_fraction = upper_vals.size / z.size
    result.value = result.upper_level - result.lower_level
    result.uncertainty = float(np.hypot(
        result.lower_std / np.sqrt(max(1, lower_vals.size)),
        result.upper_std / np.sqrt(max(1, upper_vals.size))))
    pooled = float(np.hypot(result.lower_std, result.upper_std)) / np.sqrt(2)
    result.separation_ratio = (float(result.value / pooled) if pooled > 0
                               else float("inf"))

    if result.separation_ratio < MIN_SEPARATION_RATIO:
        result.warnings.append(
            "the two plateaux overlap too much to call this a step")
        return result

    result.ok = True
    return result


def measure_step_between(
    lower: np.ndarray,
    upper: np.ndarray,
    source: str = "",
) -> StepResult:
    """
    Step height between two regions the user chose by hand.

    This is the measurement someone makes with cursors: pick a stretch of the
    lower surface, pick a stretch of the upper one, take the difference of the
    means. Nothing is inferred -- if the regions are placed badly the answer is
    wrong, and that is the operator's call to make.

    No bimodality or tilt test applies here: the user has asserted that these
    two stretches are the two levels. What is still reported is the scatter
    within each region, because a region straddling an edge shows it
    immediately as a large standard deviation.
    """
    lower = np.asarray(lower, dtype=float).ravel()
    upper = np.asarray(upper, dtype=float).ravel()
    lower = lower[np.isfinite(lower)]
    upper = upper[np.isfinite(upper)]

    result = StepResult(ok=False, method="manual: mean of two chosen regions",
                        source=source)
    if lower.size < 3 or upper.size < 3:
        result.warnings.append(
            "each region needs at least three points -- drag them wider")
        return result

    result.lower_level = float(np.mean(lower))
    result.upper_level = float(np.mean(upper))
    result.lower_std = float(np.std(lower))
    result.upper_std = float(np.std(upper))
    result.lower_fraction = lower.size / (lower.size + upper.size)
    result.upper_fraction = upper.size / (lower.size + upper.size)
    result.value = result.upper_level - result.lower_level

    # Standard error of a difference of two means.
    result.uncertainty = float(np.hypot(result.lower_std / np.sqrt(lower.size),
                                        result.upper_std / np.sqrt(upper.size)))
    pooled = float(np.hypot(result.lower_std, result.upper_std)) / np.sqrt(2)
    result.separation_ratio = (float(abs(result.value) / pooled) if pooled > 0
                               else float("inf"))
    result.confidence = "good" if result.separation_ratio >= 3 else "marginal"

    if result.value < 0:
        result.warnings.append(
            "the second region sits lower than the first, so this step is "
            "negative -- swap them if that was not intended")
    if result.separation_ratio < 3:
        result.warnings.append(
            f"the step is only {result.separation_ratio:.1f}x the scatter "
            f"inside the regions. Either the surfaces are rough compared with "
            f"the step, or a region is straddling an edge.")

    result.ok = True
    return result


@dataclass
class Aggregate:
    """A pooled measurement across several images."""

    n_used: int
    n_total: int
    mean: float
    std: float
    sem: float
    values: list[float]
    sources: list[str]
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def explain(self) -> str:
        from afm_copilot.render import pick_unit
        if self.n_used == 0:
            lines = ["No usable measurements."]
            lines.extend(f"  {name}: {why}" for name, why in self.rejected)
            return "\n".join(lines)

        factor, unit = pick_unit(abs(self.mean))
        lines = [
            f"Thickness: {self.mean / factor:.3f} +/- {self.std / factor:.3f} "
            f"{unit}  (standard deviation across {self.n_used} image"
            f"{'s' if self.n_used != 1 else ''})",
            f"  Standard error of the mean: {self.sem / factor:.3f} {unit}",
            f"  Individual values: "
            + ", ".join(f"{v / factor:.3f}" for v in self.values) + f" {unit}",
        ]
        if self.rejected:
            lines.append(f"  {len(self.rejected)} image(s) rejected:")
            lines.extend(f"    {name}: {why}" for name, why in self.rejected)
        return "\n".join(lines)


def aggregate(results: list[StepResult]) -> Aggregate:
    """
    Pool step measurements across images.

    Rejected images are reported rather than silently dropped -- if three of
    four frames failed, the surviving number needs that context.
    """
    good = [r for r in results if r.ok]
    rejected = [(r.source, r.warnings[0] if r.warnings else "not measurable")
                for r in results if not r.ok]
    values = [r.value for r in good]

    if not values:
        return Aggregate(0, len(results), float("nan"), float("nan"),
                         float("nan"), [], [], rejected)

    arr = np.asarray(values, dtype=float)
    std = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    return Aggregate(
        n_used=len(values),
        n_total=len(results),
        mean=float(np.mean(arr)),
        std=std,
        sem=std / np.sqrt(arr.size) if arr.size > 1 else 0.0,
        values=values,
        sources=[r.source for r in good],
        rejected=rejected,
    )
