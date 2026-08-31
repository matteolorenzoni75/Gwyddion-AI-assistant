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

# A population holding less than this fraction of the frame is too small to
# characterise reliably -- typical for a scratch that barely clips the image.
MIN_POPULATION_FRACTION = 0.02


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
            f"  Lower level covers {self.lower_fraction * 100:.0f}% of the "
            f"frame, upper level {self.upper_fraction * 100:.0f}%.",
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
