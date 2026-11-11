"""Offline ML never trains on private paths, operator text or raw pixels."""
import json
import numpy as np
import pytest

from afm_copilot.learning_audit import FEATURES
from afm_copilot.ml_baseline import prepare_experiment, experiment


def row(n, family, direction=None):
    basename = ("batch-%02d" % n) if direction is None else "same-" + direction
    return {
        "scan_id": n, "path": "C:/SECRET/" + basename + ".ibw",
        "sha256": ("%064x" % n), "family": family,
        "quality": "usable", "confidence": 4,
        "metrics": {k: float(n + i) for i, k in enumerate(FEATURES)},
        "notes": "sensitive human explanation",
        "artifacts": ["tilt"], "sample_group": "",
    }


def test_feature_matrix_has_only_numeric_descriptors():
    data = [row(i + 1, "terraces" if i % 2 else "pores") for i in range(14)]
    X, y, groups, report = prepare_experiment(data)
    assert X.shape == (14, len(FEATURES))
    assert len(y) == len(groups) == 14
    assert report["class_counts"] == {"pores": 7, "terraces": 7}
    assert "C:/SECRET" not in json.dumps(report)


def test_rare_class_excluded_without_modifying_original():
    data = [row(i + 1, "terraces" if i < 8 else "rough_irregular")
            for i in range(10)]
    X, y, _, report = prepare_experiment(data)
    assert len(y) == 8
    assert X.shape[0] == 8
    assert report["rare_classes_not_fitted"] == {"rough_irregular": 2}
    assert data[-1]["family"] == "rough_irregular"


def test_trace_retrace_paired_in_same_cv_group():
    data = [row(1, "terraces", "trace"),
            row(2, "terraces", "retrace")]
    data += [row(i, "terraces" if i % 2 else "pores") for i in range(3, 17)]
    _, _, groups, info = prepare_experiment(data)
    assert groups[0] == groups[1]
    assert info["paired_trace_retrace_candidates_kept_together"] == 1


def test_conflicting_identical_bytes_excluded():
    data = [row(i + 1, "terraces" if i % 2 else "pores") for i in range(12)]
    data[1]["sha256"] = data[0]["sha256"]
    X, _, _, info = prepare_experiment(data)
    assert X.shape[0] == 10
    assert info["conflicting_rows_held"] == 2


def test_offline_training_reports_no_deployed_or_saved_model():
    pytest.importorskip("sklearn", minversion="1.3")
    data = [row(i + 1, "terraces" if i % 2 else "pores") for i in range(42)]
    report = experiment(data)
    assert len(report["scores"]) == 2
    assert report["cv_folds"] == 3
    assert report["model_saved"] is False
    assert report["model_deployed"] is False
    assert report["test_set_independent"] is False
    assert "C:/SECRET" not in json.dumps(report)
    assert "sensitive" not in json.dumps(report)
