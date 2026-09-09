"""
How blunt the tip was, and what that does to every width in the image.

An AFM image is the surface dilated by the probe, so a lateral size is the
sample's only after the tip is accounted for. The catalog does this by hand
already -- a DNA filament 1.34 nm tall reads 40 nm wide and is really about 10
-- and this is that arithmetic, with the radius found rather than assumed where
the image allows it.

**Gwyddion's own blind estimation is not reachable from here.** Its `tip_blind`
module is registered RUN_INTERACTIVE only, so it cannot run headless, and the
low-level `gwy_tip_estimate_partial` binding destroys the data field it is
given -- the field comes back with xres 0, both the argument and the return.
Both were tested. So the bound below is computed on this side instead.

The estimate is deliberately modest. It does not reconstruct the tip's shape;
it answers the one question the width correction needs: **how sharp can the tip
possibly have been?** An image cannot be sharper than the probe that made it,
so the sharpest peak in the frame is an upper bound on the tip's own radius.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# The probe in routine use here, and the fallback when an image has nothing
# sharp enough to bound the tip with. Stated by the user: AC160, the standard
# silicon pyramidal probe at about 300 kHz.
AC160_RADIUS = 10e-9
AC160_RADIUS_COATED = 30e-9

# A peak needs this many pixels across its top before a curvature fitted to it
# means anything.
MIN_PEAK_PIXELS = 5

# The sharpest few peaks bound the tip; the very sharpest is as likely to be
# noise, so a low percentile is taken rather than the minimum.
SHARPEST_PERCENTILE = 5.0

# A fitted paraboloid this much larger than the window it was fitted in is not
# constrained by it, and is discarded.
MAX_FIT_REACH = 8.0

# And the fit has to describe the patch. Below this correlation between height
# and squared distance, the "summit" is noise.
MIN_FIT_QUALITY = 0.90


@dataclass
class Tip:
    """What we believe about the probe, and on what grounds."""

    radius: float                    # metres, the one to use
    source: str                      # "image" | "nominal" | "given"
    bound: float | None = None       # what the image could prove, if anything
    nominal: float = AC160_RADIUS
    peaks_used: int = 0

    @property
    def measured(self) -> bool:
        return self.source == "image"

    def describe(self) -> str:
        if self.source == "given":
            return f"tip radius given as {self.radius * 1e9:.0f} nm"

        if self.bound is None:
            return (f"assuming the nominal {self.nominal * 1e9:.0f} nm of an "
                    "AC160 — nothing in this image is sharp enough to say "
                    "anything about the tip")

        if self.source == "image":
            return (f"the tip is no blunter than {self.radius * 1e9:.0f} nm, "
                    f"from the {self.peaks_used} sharpest features here — "
                    f"tighter than the nominal {self.nominal * 1e9:.0f} nm, so "
                    "it is what gets used")

        # The usual case: an upper bound looser than what the probe should be.
        return (f"assuming the nominal {self.nominal * 1e9:.0f} nm of an "
                f"AC160. The image itself only proves the tip is no blunter "
                f"than {self.bound * 1e9:.0f} nm, which at this pixel size is "
                "no help — a scan cannot bound a tip sharper than its own "
                "sampling")


def feature_radius(apparent_width: float, tip_radius: float) -> float:
    """
    The radius an object would have, measured with a perfect point.

    The geometry the user's catalog derives: a feature of radius r touched by a
    tip of radius R appears 2x wide with x = sqrt(R*r), so

        apparent width = 4 * sqrt(R * r)   and   r = (apparent width)^2 / 16R

    Their worked example is a DNA filament: 40 nm apparent with a 10 nm tip
    gives 10 nm, which is the number they quote. **It is a radius, not a
    width** -- the catalog's own note writes "W (real) ~ 10 nm" for it, and
    reading that as a width doubles every answer. Anything that reports a size
    to a person has to say which of the two it is.

    The relation holds while the feature is comparable to the tip or smaller.
    Beyond that it inverts and starts reporting objects *wider* than they were
    measured: a 469 nm particle with a 10 nm probe came back as 2744 nm across,
    and one scan reached 67 micrometres. A tip only ever makes things look
    wider, so a correction that enlarges an object is the formula outside its
    range. The radius is capped at half the measured width, and where the cap
    bites the reported size equals the measured one -- which is how the caller
    can see that no correction was applied.
    """
    if tip_radius <= 0 or apparent_width <= 0:
        return apparent_width / 2.0 if apparent_width > 0 else 0.0
    return min((apparent_width ** 2) / (16.0 * tip_radius),
               apparent_width / 2.0)


def sharpest_feature(data: np.ndarray, pixel_size: float) -> Tip | None:
    """
    An upper bound on the tip radius, from the sharpest peaks in the image.

    Every summit in an AFM image is at least as round as the tip that traced
    it, so the roundest-fitting peak bounds nothing but the sharpest one bounds
    the tip. Each local maximum gets a paraboloid fitted to its neighbourhood;
    for z = z0 - r^2 / (2R), the curvature gives R directly.

    Returns None when the image has no peaks worth fitting -- a flat substrate,
    a pitted surface, a frame full of one large object. That is the common case
    and it is why there is a nominal fallback.
    """
    from scipy import ndimage

    values = np.asarray(data, dtype=float)
    if values.size < 256 or not np.isfinite(values).any():
        return None

    filled = np.nan_to_num(values, nan=float(np.nanmedian(values)))
    # Local maxima that also stand clear of their surroundings.
    window = ndimage.maximum_filter(filled, size=5, mode="nearest")
    peaks = (filled >= window) & (filled > np.percentile(filled, 90))
    labels, count = ndimage.label(peaks)
    if count == 0:
        return None

    radii = []
    half = MIN_PEAK_PIXELS // 2 + 1
    reach = half * pixel_size
    for cy, cx in ndimage.center_of_mass(peaks, labels,
                                         range(1, count + 1)):
        y, x = int(round(cy)), int(round(cx))
        if (y - half < 0 or x - half < 0
                or y + half >= values.shape[0] or x + half >= values.shape[1]):
            continue
        patch = filled[y - half:y + half + 1, x - half:x + half + 1]
        radius = _apex_radius(patch, pixel_size)
        if radius is None:
            continue
        # A paraboloid far larger than the window it was fitted in is not
        # measured by that window -- it is the window failing to constrain it.
        # This is what let the flat parts of a scan return a tip micrometres
        # across, and it is also why the answer can never be tighter than the
        # sampling: a scan cannot bound a tip sharper than its own pixels.
        if pixel_size <= radius <= MAX_FIT_REACH * reach:
            radii.append(radius)

    if len(radii) < 3:
        return None
    # The sharpest summit bounds the tip; a percentile rather than the outright
    # minimum, because the single sharpest is as likely to be a spike.
    bound = float(np.percentile(radii, SHARPEST_PERCENTILE))
    if not math.isfinite(bound) or bound <= 0:
        return None
    return Tip(radius=bound, source="image", bound=bound,
               peaks_used=len(radii))


def _apex_radius(patch: np.ndarray, pixel_size: float) -> float | None:
    """Radius of the paraboloid that best fits one summit."""
    size = patch.shape[0]
    offsets = (np.arange(size) - size // 2) * pixel_size
    yy, xx = np.meshgrid(offsets, offsets, indexing="ij")
    r2 = (xx ** 2 + yy ** 2).ravel()
    z = patch.ravel()
    if not np.isfinite(z).all():
        return None
    # z = z0 - r^2 / (2R): a straight line in r^2 whose slope is -1/(2R).
    if np.ptp(z) <= 0 or np.ptp(r2) <= 0:
        return None
    quality = abs(float(np.corrcoef(r2, z)[0, 1]))
    if not math.isfinite(quality) or quality < MIN_FIT_QUALITY:
        return None                     # the patch is not a summit shape
    slope, _ = np.polyfit(r2, z, 1)
    if slope >= 0:
        return None                     # not a summit
    return float(-1.0 / (2.0 * slope))


def for_scan(data: np.ndarray, pixel_size: float, *,
             coated: bool = False, given: float | None = None) -> Tip:
    """
    The tip to use for this scan, in order of how much it is worth trusting.

    Measured from the image where the image allows it; otherwise the nominal
    radius of the probe in routine use, said out loud rather than folded in
    silently. The difference matters: a 50 nm particle reads about 90 nm wide
    through a 10 nm tip and 155 nm through a coated 30 nm one, so a width
    quoted without saying which was assumed is not a measurement.
    """
    nominal = AC160_RADIUS_COATED if coated else AC160_RADIUS
    if given is not None:
        return Tip(radius=given, source="given", nominal=nominal)

    measured = sharpest_feature(data, pixel_size)
    if measured is None:
        return Tip(radius=nominal, source="nominal", nominal=nominal)

    # An image gives an upper bound, and usually a loose one: it cannot resolve
    # anything finer than its own pixels, so a scan at 10 nm per pixel proves
    # only that the tip is no blunter than some hundreds of nanometres. Useless
    # against a probe that should be 10 nm to begin with.
    #
    # So the tighter of the two wins, and both are kept. Note what this cannot
    # do: an upper bound can show a tip is sharp, never that it is worn. A
    # loose bound on a scan full of sharp-looking features is a hint about the
    # tip and nothing more -- see knowledge/the-tip-shows-itself-to-the-eye.md.
    if measured.radius < nominal:
        measured.nominal = nominal
        measured.bound = measured.radius
        return measured
    return Tip(radius=nominal, source="nominal", bound=measured.radius,
               nominal=nominal, peaks_used=measured.peaks_used)
