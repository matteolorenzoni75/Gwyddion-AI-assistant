"""
Corrections that apply to a region, not to the frame.

Everything else in this pipeline treats a scan as a whole: level it, align its
rows, filter it. A large class of real defects is not like that. A patch of
dirt sits in one place. A broad concave dish, left where the tip dragged and
the feedback took its time recovering, occupies a corner. The rest of the image
is fine, and a whole-frame correction strong enough to fix the corner would
damage everything else.

Two repairs, and they are not the same operation:

* **Erase and fill.** The pixels are not measurements at all -- dirt, a
  dropout, a speck. Nothing of the surface is under them, so they are replaced
  by what the surrounding pixels imply. Gwyddion's Remove Spots does this
  interactively, and `mark_outliers` + `interpolate_under_mask` does it here
  from a computed mask.

* **Lift back into place.** The pixels *are* measurements; they simply sit at
  the wrong height, because the instrument lost the surface and found it again
  a little lower. Erasing them throws away real texture. What they need is the
  broad shape corrected while the fine detail is kept, which is what this
  module adds.

The user reports the second kind is frequent, and until now there was nothing
that could do it.

**Neither is ever applied on its own.** The user's instruction, given twice:
deciding to flatten away corpuscles has to be put to the operator, or we risk
planing off nanoparticles. Nothing here can tell a speck of dirt from a
particle that is the point of the experiment -- that is a fact about the
sample, not about the image. So these functions find candidates and describe
them, and something else asks.
"""

from __future__ import annotations

import numpy as np

# A repairable dish is broad and smooth. Below this many pixels it is a speck
# and belongs to the erase-and-fill route instead.
MIN_REGION_PIXELS = 400

# How far out from the region to read the surrounding surface, as a share of
# the region's own width. Wide enough to see past the disturbance, narrow
# enough that the far side of the image does not set the answer.
SURROUND_REACH = 0.5


def lift_region(data: np.ndarray, region: np.ndarray,
                degree: int = 2) -> np.ndarray:
    """
    Bring a depressed region back to the level its surroundings imply.

    The broad shape inside the region is replaced by the shape the ring around
    it extrapolates to; everything finer than that shape is untouched. So a
    dish left by the tip dragging is flattened out while the texture inside it
    survives -- which is the whole point, since that texture is the sample.

    Returns the data unchanged when the region is too small to be this kind of
    defect, or when there is not enough surrounding surface to say what the
    inside should have been.
    """
    from scipy import ndimage

    values = np.asarray(data, dtype=float)
    inside = np.asarray(region, dtype=bool)
    if inside.sum() < MIN_REGION_PIXELS:
        return values

    # A ring around the region, wide in proportion to the region itself.
    width = max(3, int(SURROUND_REACH * np.sqrt(inside.sum())))
    grown = ndimage.binary_dilation(inside, iterations=width)
    ring = grown & ~inside & np.isfinite(values)
    if ring.sum() < 6 * (degree + 1) * (degree + 2):
        return values

    design = _polynomial_terms(values.shape, degree)
    try:
        outside_fit, _, _, _ = np.linalg.lstsq(
            design[ring.ravel()], values[ring], rcond=None)
        inside_fit, _, _, _ = np.linalg.lstsq(
            design[inside.ravel()], values[inside], rcond=None)
    except np.linalg.LinAlgError:
        return values

    # Swap the region's own broad shape for the one the ring implies. The
    # difference is added rather than the surface replaced, so nothing finer
    # than the fitted order is disturbed.
    surfaces = design @ (outside_fit - inside_fit)
    out = values.copy()
    out[inside] = values[inside] + surfaces.reshape(values.shape)[inside]
    return out


def find_dishes(flat: np.ndarray, depth_ratio: float = 3.0) -> np.ndarray:
    """
    Broad, smooth depressions -- the kind the tip leaves when it drags.

    Distinguished from real pits by being large and *smooth*: a pore has
    steep walls and a floor at a definite level, while a dragged dish sags.
    Measured as a region sitting well below a heavily smoothed version of the
    surface, which is blind to anything sharp.
    """
    from scipy import ndimage

    values = np.nan_to_num(np.asarray(flat, dtype=float))
    window = max(9, min(values.shape) // 6)
    broad = ndimage.uniform_filter(values, size=window, mode="nearest")
    sag = broad - np.median(broad)

    # Measured against the surface's own roughness, not against the smoothed
    # variation. The smoothed variation collapses towards zero on a clean
    # surface, and then half the frame clears any multiple of it -- the same
    # trap that made a noise measure call a grating 69% noise.
    scale = 1.4826 * float(np.median(np.abs(values - np.median(values))))
    if scale <= 0:
        return np.zeros(values.shape, dtype=bool)

    dishes = sag < -depth_ratio * scale
    labels, count = ndimage.label(dishes)
    if count == 0:
        return dishes
    keep = np.zeros(values.shape, dtype=bool)
    areas = np.bincount(labels.ravel())
    for index in range(1, count + 1):
        if areas[index] >= MIN_REGION_PIXELS:
            keep |= labels == index
    return keep


def _polynomial_terms(shape: tuple[int, int], degree: int) -> np.ndarray:
    """Design matrix of x^i y^j terms, one row per pixel."""
    rows, cols = shape
    y, x = np.mgrid[0:rows, 0:cols]
    x = (x / max(cols - 1, 1) - 0.5).ravel()
    y = (y / max(rows - 1, 1) - 0.5).ravel()
    terms = [np.ones_like(x)]
    for total in range(1, degree + 1):
        for i in range(total + 1):
            terms.append((x ** i) * (y ** (total - i)))
    return np.column_stack(terms)
