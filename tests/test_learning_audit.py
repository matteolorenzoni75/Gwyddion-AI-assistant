"""Private AFM label audit: aggregation, leakage gates and no identifiers."""
import json

from afm_copilot.learning_audit import FEATURES, audit_rows


def row(n, family="terraces", role="unassigned", group="", metrics=None,
        quality="usable", sha=None):
    return {"scan_id": n, "path": "C:/secret/Partner_{}.ibw".format(n),
            "family": family, "dataset_role": role, "sample_group": group,
            "sha256": sha, "quality": quality,
            "metrics": metrics if metrics is not None else
            {k: float(n) for k in FEATURES[:8]},
            "notes": "confidential specimen"}


def test_absent_labels_are_not_ready():
    result = audit_rows([row(1, family=None)])
    assert result["labeled"] == 0
    assert not result["training_ready"]
    assert "no_labels" in result["blockers"]


def test_label_counts_and_missing_descriptors():
    data = [row(1), row(2, family="pores", metrics={}),
            row(3, family="uncertain", quality="review")]
    report = audit_rows(data)
    assert report["labeled"] == 3
    assert report["morphology_counts"] == {"pores": 1, "terraces": 1, "uncertain": 1}
    assert report["with_at_least_5_numeric_descriptors"] == 1
    assert report["missing_numeric_feature_counts"][FEATURES[0]] == 1
    assert report["eligible_for_future_training_review"] == 2


def test_sample_group_leak_and_identical_bytes_are_blocked():
    data = [row(1, role="train", group="PRIVATE-A", sha="abc"),
            row(2, role="validation", group="PRIVATE-A", sha="def"),
            row(3, role="holdout", group="PRIVATE-B", sha="abc")]
    report = audit_rows(data)
    assert report["cross_partition_specimen_groups"] == 1
    assert report["cross_partition_identical_bytes"] == 1
    assert "specimen_group_crosses_splits" in report["blockers"]
    assert "identical_content_crosses_splits" in report["blockers"]


def test_audit_never_exposes_paths_groups_notes_or_hashes():
    data = [row(1, role="train", group="PRIVATE-GENOA-123",
                sha="abcdef123PRIVATE")]
    text = json.dumps(audit_rows(data))
    for secret in ("Partner_1", "PRIVATE-GENOA-123", "confidential specimen",
                   "abcdef123PRIVATE", "C:/secret"):
        assert secret not in text


def test_nonfinite_metrics_count_as_missing():
    data = [row(1, metrics={"tilt": float("nan"), "row_banding": float("inf"),
                            "object_count": 3})]
    report = audit_rows(data)
    assert report["missing_numeric_feature_counts"]["tilt"] == 1
    assert report["with_at_least_5_numeric_descriptors"] == 0


def test_explicit_adequate_split_can_clear_audit_gates():
    rows = []
    for i in range(42):
        if i < 24:
            role, group = "train", "G" + str(i // 4)
        elif i < 34:
            role, group = "validation", "V" + str((i - 24) // 2)
        else:
            role, group = "holdout", "H" + str((i - 34) // 2)
        rows.append(row(i + 1, family="terraces" if i % 2 else "pores",
                        role=role, group=group,
                        sha="hash-" + str(i)))
    audit = audit_rows(rows)
    assert audit["training_ready"]
    assert not audit["blockers"]
    assert audit["model_trained"] is False
