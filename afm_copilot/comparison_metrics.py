"""Numerical support for AFM manual-versus-automatic correction review.

Do not mistake similarity to a manual image for ground-truth physical
accuracy. Geometry and units must match; median Z offset is removed only
for comparing surface *shape*, not metrology or absolute potential.
"""
from __future__ import annotations

import numpy as np


def shape_comparison(reference, candidate) -> dict:
    if (reference.data.shape != candidate.data.shape
        or reference.xy_unit != "m" or candidate.xy_unit != "m"
        or reference.z_unit != "m" or candidate.z_unit != "m"
        or not np.isclose(reference.xreal, candidate.xreal, rtol=1e-7)
        or not np.isclose(reference.yreal, candidate.yreal, rtol=1e-7)):
        return {"comparable": False, "reason": "different grid or calibration"}
    a = np.asarray(reference.data, dtype=float)
    b = np.asarray(candidate.data, dtype=float)
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        return {"comparable": False, "reason": "nonfinite pixels"}
    delta = b - a
    delta -= np.median(delta)
    rmse = float(np.sqrt(np.mean(delta ** 2)))
    p95 = float(np.quantile(np.abs(delta), .95))
    return {
        "comparable": True, "shape_rmse_nm": round(rmse * 1e9, 4),
        "difference_p95_nm": round(p95 * 1e9, 4),
        "note": "Similarity to a human revision, not validated accuracy.",
    }
