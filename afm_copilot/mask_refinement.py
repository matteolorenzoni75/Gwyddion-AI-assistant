"""Previewable morphology-protection mask for a Gwyddion background fit.

Mask creation is NOT a defect-erasing filter. A user must preview and approve
which regions are EXCLUDED from the plane/background fit. Neither the mask
nor the fitted image implies that those regions are noise or should be removed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage


@dataclass
class MaskProposal:
    mask: np.ndarray
    threshold_nm: float
    masked_fraction: float
    min_unmasked_row_fraction: float
    safe_for_fit: bool
    reason: str


def robust_plane(data: np.ndarray) -> np.ndarray:
    """Estimate a low-order plane without committing any correction."""
    z = np.asarray(data, dtype=float)
    if z.ndim != 2 or min(z.shape) < 16 or not np.isfinite(z).all():
        raise ValueError("A complete finite height map is required")
    h, w = z.shape
    yy, xx = np.indices(z.shape, dtype=float)
    A = np.column_stack((np.ones(z.size), xx.ravel()/max(1,w-1),
                         yy.ravel()/max(1,h-1)))
    flat = z.ravel()
    include = np.ones(z.size, dtype=bool)
    for _ in range(4):
        coef, *_ = np.linalg.lstsq(A[include], flat[include], rcond=None)
        residual = flat - A @ coef
        median = np.median(residual[include])
        mad = 1.4826 * np.median(np.abs(residual[include] - median))
        if mad <= 0:
            break
        new = np.abs(residual - median) <= max(3*mad, 1e-12)
        if new.mean() < 0.5:
            break
        include = new
    return (A @ coef).reshape(z.shape)


def propose_mask(data: np.ndarray, *, threshold_nm: float,
                 mode: str = "both", dilation_pixels: int = 2,
                 estimated_plane: np.ndarray | None = None) -> MaskProposal:
    """Exclude candidate features, while refusing masks with poor background.

    The threshold is in nm after a *provisional* robust plane subtraction.
    The fitted plane is only used to propose a mask, not to correct the scan.
    """
    if mode not in ("both", "raised", "sunken"):
        raise ValueError("Unknown mask polarity")
    if not 0.1 <= threshold_nm <= 10000:
        raise ValueError("Mask threshold must be in nm (0.1 to 10000)")
    if dilation_pixels not in (0, 1, 2, 3, 4):
        raise ValueError("Mask dilation range is 0..4 pixels")
    z = np.asarray(data, dtype=float)
    plane = robust_plane(z) if estimated_plane is None else np.asarray(
        estimated_plane, dtype=float)
    if plane.shape != z.shape or not np.isfinite(plane).all():
        raise ValueError("Invalid provisional background")
    residual = z - plane
    # Local median suppresses isolated one-pixel spikes that must not
    # masquerade as morphology to be protected by a background fit.
    local = ndimage.median_filter(residual, size=3, mode="nearest")
    center = float(np.median(local))
    threshold = threshold_nm * 1e-9
    if mode == "raised":
        proposed = local - center > threshold
    elif mode == "sunken":
        proposed = local - center < -threshold
    else:
        proposed = np.abs(local - center) > threshold
    # Remove single tiny patches rather than treating lone hot pixels as
    # large sample features. Keep them in raw image; don't interpolate them.
    labels, count = ndimage.label(proposed)
    if count:
        component_sizes = np.bincount(labels.ravel())
        min_area = max(4, int(z.size * 0.00005))
        proposed &= (component_sizes[labels] >= min_area) & (labels > 0)
    if dilation_pixels:
        proposed = ndimage.binary_dilation(proposed, iterations=dilation_pixels)
    fraction = float(proposed.mean())
    per_row = 1.0 - proposed.mean(axis=1)
    min_row = float(np.min(per_row))
    if fraction < 0.01:
        safe, reason = False, "Mask covers too little: no distinct features"
    elif fraction > 0.40:
        safe, reason = False, "Too many masked pixels for a reliable background fit"
    elif min_row < 0.25:
        safe, reason = False, "Some rows have too little unmasked background"
    else:
        safe, reason = True, "Candidate mask requires visual operator approval"
    return MaskProposal(
        mask=proposed.astype(bool), threshold_nm=float(threshold_nm),
        masked_fraction=fraction, min_unmasked_row_fraction=min_row,
        safe_for_fit=safe, reason=reason,
    )
