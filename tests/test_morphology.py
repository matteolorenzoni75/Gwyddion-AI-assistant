"""Semantic reviews are explicit, strict and conservative."""

import json

import numpy as np
import pytest

from afm_copilot.morphology import (MorphologyReview, background_support,
                                    load_reviews, upsert_review)


def test_reviews_are_loaded_by_scan_stem(tmp_path):
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps({"reviews": [{
        "scan": "scan-053.gwy",
        "family": "granular_continuous",
        "effect": "restrict",
        "source": "vision-review",
        "evidence": ["features tile the frame", "no majority background"],
    }]}), encoding="utf-8")

    reviews = load_reviews(path)

    assert set(reviews) == {"scan-053"}
    assert reviews["scan-053"].restricts_automatic_masking
    assert len(reviews["scan-053"].evidence) == 2


@pytest.mark.parametrize("field,value", [
    ("family", "grains-maybe"),
    ("effect", "apply-polynomial"),
])
def test_unknown_review_values_are_rejected(tmp_path, field, value):
    record = {
        "scan": "scan-053",
        "family": "granular_continuous",
        "effect": "restrict",
    }
    record[field] = value
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"reviews": [record]}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_reviews(path)


def test_duplicate_reviews_are_rejected(tmp_path):
    record = {"scan": "same", "family": "uncertain"}
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps([record, record]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        load_reviews(path)


def test_gui_style_upsert_preserves_other_scan_reviews(tmp_path):
    path = tmp_path / "reviews.json"
    first = MorphologyReview(
        scan="scan-a", family="uncertain", source="gui-operator")
    second = MorphologyReview(
        scan="scan-b", family="granular_continuous", effect="restrict",
        source="gui-operator", evidence=("texture fills the field",))
    changed = MorphologyReview(
        scan="scan-a", family="terraces", source="gui-operator")

    upsert_review(path, first)
    upsert_review(path, second)
    upsert_review(path, changed)
    loaded = load_reviews(path)

    assert set(loaded) == {"scan-a", "scan-b"}
    assert loaded["scan-a"].family == "terraces"
    assert loaded["scan-b"].restricts_automatic_masking
    assert not path.with_suffix(".json.tmp").exists()


def test_background_support_separates_an_object_from_its_quiet_base():
    rng = np.random.default_rng(41)
    data = rng.normal(0.0, 0.5e-9, (128, 128))
    mask = np.zeros_like(data, dtype=bool)
    mask[42:86, 44:84] = True
    data[mask] += 80e-9

    evidence = background_support(data, mask)

    assert evidence.valid
    assert evidence.unmasked_fraction > 0.80
    assert evidence.worst_row_support > 0.60
    assert evidence.largest_region_fraction > 0.99
    assert evidence.roughness_ratio < 0.10


def test_background_support_exposes_continuous_texture_behind_a_mask():
    rng = np.random.default_rng(42)
    data = rng.normal(0.0, 1.0, (128, 128))
    for _ in range(5):
        data = (data + np.roll(data, 1, axis=0)
                + np.roll(data, 1, axis=1)) / 3.0
    mask = np.zeros_like(data, dtype=bool)
    mask[::4, ::4] = True

    evidence = background_support(data, mask)

    assert evidence.valid
    assert evidence.roughness_ratio > 0.85
    assert evidence.gradient_ratio > 0.85
    assert evidence.texture_coverage > 0.75


def test_background_support_rejects_a_mask_that_leaves_too_little_surface():
    data = np.ones((64, 64), dtype=float)
    mask = np.ones_like(data, dtype=bool)
    mask[:, :20] = False

    evidence = background_support(data, mask)

    assert not evidence.valid
    assert evidence.unmasked_fraction < 0.40
