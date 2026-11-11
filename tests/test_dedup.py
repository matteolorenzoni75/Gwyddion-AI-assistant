"""No source/label deletion; keep distinct trace and retrace acquisitions."""
import json

from afm_copilot.dedup import (_direction, plan_rows, safe_report,
                              prepare_private_selection)


def row(n, name, digest=None, family="terraces", quality="unknown",
        confidence=3, metrics=None):
    return {"scan_id": n, "path": "C:/lab/" + name,
            "sha256": digest, "family": family,
            "quality": quality, "confidence": confidence,
            "metrics": metrics or {}, "notes": "private sample"}


def digest(character):
    return character * 64


def test_exact_copy_collapses_to_one_without_destroying_labels():
    rows = [row(1, "one.ibw", digest("a")),
            row(2, "duplicate.ibw", digest("a")),
            row(3, "other.ibw", digest("b"))]
    result = plan_rows(rows)
    assert result["registered_labeled"] == 3
    assert result["exact_duplicates_excluded"] == 1
    assert result["distinct_labeled_after_exact_dedup"] == 2
    assert result["eligible_unique_labeled"] == 2
    assert result["_private_selection"]["candidate_ids"] == [1, 3]


def test_conflicting_labels_on_identical_bytes_are_quarantined():
    rows = [row(1, "one.ibw", digest("a"), "terraces"),
            row(2, "two.ibw", digest("a"), "pores")]
    result = plan_rows(rows)
    assert result["conflicting_exact_copy_groups"] == 1
    assert result["conflicting_rows_held"] == 2
    assert result["eligible_unique_labeled"] == 0


def test_trace_and_retrace_remain_distinct_when_data_differ():
    rows = [row(1, "sample_trace.ibw", digest("a")),
            row(2, "sample_retrace.ibw", digest("b"))]
    result = plan_rows(rows)
    assert result["eligible_unique_labeled"] == 2
    assert result["potential_trace_retrace_pairs_by_name"] == 1
    assert result["exact_duplicates_excluded"] == 0


def test_same_bytes_retrace_not_double_counted():
    rows = [row(1, "sample_trace.ibw", digest("a")),
            row(2, "sample_retrace.ibw", digest("a"))]
    result = plan_rows(rows)
    assert result["eligible_unique_labeled"] == 1
    assert result["potential_trace_retrace_pairs_by_name"] == 0


def test_name_alone_does_not_remove_scans():
    rows = [row(1, "sample.ibw", digest("a")),
            row(2, "sample.tiff", digest("b"))]
    result = plan_rows(rows)
    assert result["eligible_unique_labeled"] == 2


def test_rejected_or_review_quality_not_training_candidates():
    rows = [row(1, "a.ibw", digest("a"), quality="reject"),
            row(2, "b.ibw", digest("b"), quality="review"),
            row(3, "c.ibw", digest("c"))]
    result = plan_rows(rows)
    assert result["eligible_unique_labeled"] == 1
    assert result["quality_or_uncertain_excluded"] == 2


def test_missing_hashes_not_combined_even_with_same_names():
    rows = [row(1, "a/scan.ibw"), row(2, "b/scan.ibw")]
    result = plan_rows(rows)
    assert result["eligible_unique_labeled"] == 2


def test_safe_report_never_leaks_identifiers_paths_or_digests():
    rows = [row(13, "SECRET_name.ibw", digest("a")),
            row(14, "SECRET_name_copy.ibw", digest("a"))]
    summary = json.dumps(safe_report(rows))
    for word in ("SECRET", "C:/lab", digest("a"), '"candidate_ids"',
                 '"conflict_ids"', '"scan_id"', "private sample"):
        assert word not in summary


def test_direction_recognizes_only_clear_terminal_tokens():
    assert _direction("C:/folder/a_trace.ibw") == ("a", "trace")
    assert _direction("C:/folder/a_retrace.tiff") == ("a", "retrace")
    assert _direction("C:/folder/traceability.ibw") is None


def test_prepare_selection_is_private_reversible_and_no_originals_deleted(tmp_path):
    rows = [row(1, "first.ibw", digest("a")),
            row(2, "copy.ibw", digest("a")),
            row(3, "second.ibw", digest("b"))]
    private = tmp_path / "private" / "PRIVATE_dedup_selection.json"
    result = prepare_private_selection(rows, private)
    assert private.is_file()
    payload = json.loads(private.read_text(encoding="utf-8"))
    assert payload["candidate_scan_ids"] == [1, 3]
    assert payload["suppressed_exact_copy_scan_ids"] == [2]
    assert payload["no_original_files_changed"] is True
    assert payload["not_a_validated_training_split"] is True
    assert result["exact_duplicates_excluded"] == 1
    assert "candidate_scan_ids" not in str(result)
