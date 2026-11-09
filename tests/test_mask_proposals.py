"""The candidate mask catalogue is explicit and inspectable."""

import numpy as np

from afm_copilot.mask_proposals import DEFAULT_METHODS, mask_statistics


def test_the_candidates_cover_independent_grain_evidence():
    keys = {method.key for method in DEFAULT_METHODS}
    assert {"height_high", "slope", "curvature", "edge", "otsu", "watershed"} <= keys
    assert all(method.gwy_func for method in DEFAULT_METHODS)


def test_mask_statistics_reports_shape_not_a_semantic_label():
    mask = np.zeros((12, 12), dtype=bool)
    mask[1:3, 1:3] = True
    mask[7:10, 8:11] = True
    stats = mask_statistics(mask)
    assert stats["fraction"] == round(13 / 144, 6)
    assert stats["grains"] == 2
    assert stats["edge_touching_grains"] == 0
