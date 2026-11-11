"""Synoptic shape metric is physical, not a misleading image-colour score."""
import numpy as np

from afm_copilot.comparison_metrics import shape_comparison
from afm_copilot.gwy_io import Channel


def test_global_height_zero_shift_does_not_look_like_surface_error():
    base = np.arange(64, dtype=float).reshape(8, 8) * 1e-9
    human = Channel("Height", base, 2e-6, 2e-6)
    automated = Channel("Height", base + 31e-9, 2e-6, 2e-6)
    result = shape_comparison(human, automated)
    assert result["comparable"]
    assert result["shape_rmse_nm"] == 0


def test_pixel_difference_is_detected_without_false_claim_of_accuracy():
    base = np.zeros((16, 16), dtype=float)
    changed = base.copy()
    changed[5:10, 5:10] = 9e-9
    result = shape_comparison(
        Channel("Height", base, 3e-6, 3e-6),
        Channel("Height", changed, 3e-6, 3e-6))
    assert result["comparable"]
    assert result["shape_rmse_nm"] > 0
    assert "not validated" in result["note"]


def test_mismatched_calibration_refused():
    base = np.zeros((16, 16))
    result = shape_comparison(
        Channel("Height", base, 1e-6, 1e-6),
        Channel("Height", base, 2e-6, 1e-6))
    assert not result["comparable"]


def test_synoptic_window_uses_splitter_and_visible_navigation():
    from PySide6.QtWidgets import QApplication, QSplitter
    from afm_copilot.compare_gui import CompareWindow
    app = QApplication.instance() or QApplication([])
    window = CompareWindow()
    try:
        assert isinstance(window.viewer_splitter, QSplitter)
        assert len(window.viewers) == 3
        assert window.previous_button.text()
        assert window.next_button.text()
        assert window.verdict.maximumWidth() <= 420
        assert window.minimumWidth() <= 850
    finally:
        window.close()
