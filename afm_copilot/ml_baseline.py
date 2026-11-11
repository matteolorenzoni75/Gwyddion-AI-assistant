"""Offline-only supervised morphology baseline from expert-approved AFM labels.

Evaluates numerical descriptors; no access to image pixels or source paths in
the model feature matrix. Keeps trace/retrace candidates together in CV.
Results are *internal exploratory diagnostics*, not independent validation.
No model is saved, deployed, or connected to image-processing decisions.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from afm_copilot.dedup import plan_rows
from afm_copilot.labeling import DEFAULT_DB, get_scans
from afm_copilot.learning_audit import FEATURES

MIN_CLASS_EXAMPLES = 5


def prepare_experiment(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    plan = plan_rows(rows)
    ids = set(plan["_private_selection"]["candidate_ids"])
    selected = [r for r in rows if r["scan_id"] in ids]
    counts = Counter(r["family"] for r in selected)
    excluded_classes = {family for family, n in counts.items() if n < MIN_CLASS_EXAMPLES}
    selected = [r for r in selected if r["family"] not in excluded_classes]

    # Union-Find for related trace/retrace scans. File identities are never
    # sent into the predictor, only used to constrain evaluation folds.
    parent = {r["scan_id"]: r["scan_id"] for r in selected}
    def root(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    for a, b in plan["_private_selection"]["possible_trace_retrace_pairs"]:
        if a in parent and b in parent:
            pa, pb = root(a), root(b)
            parent[max(pa, pb)] = min(pa, pb)
    groups = np.asarray([root(r["scan_id"]) for r in selected], dtype=int)
    X = np.asarray([
        [float((r.get("metrics") or {}).get(key))
         if type((r.get("metrics") or {}).get(key)) in (int, float)
         and math.isfinite((r.get("metrics") or {}).get(key))
         else np.nan
         for key in FEATURES]
        for r in selected
    ], dtype=float)
    y = np.asarray([r["family"] for r in selected])
    metadata = {
        "selected_after_exact_dedup": plan["eligible_unique_labeled"],
        "selected_for_baseline": len(selected),
        "rare_classes_not_fitted": dict(sorted(
            (k, v) for k, v in counts.items() if k in excluded_classes)),
        "class_counts": dict(sorted(Counter(y.tolist()).items())),
        "feature_count": len(FEATURES),
        "paired_trace_retrace_candidates_kept_together": plan["potential_trace_retrace_pairs_by_name"],
        "duplicates_excluded": plan["exact_duplicates_excluded"],
        "conflicting_rows_held": plan["conflicting_rows_held"],
    }
    return X, y, groups, metadata


def experiment(rows: list[dict]) -> dict:
    """Leakage-aware provisional CV, no persistent model fitted."""
    try:
        from sklearn.dummy import DummyClassifier
        from sklearn.ensemble import ExtraTreesClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.model_selection import StratifiedGroupKFold
        from sklearn.pipeline import make_pipeline
    except ImportError as exc:
        raise RuntimeError(
            "scikit-learn not installed. Install only the optional ML extra: "
            "python -m pip install -e '.[ml]'"
        ) from exc

    X, y, groups, info = prepare_experiment(rows)
    if len(y) < 30 or len(set(y)) < 2:
        raise ValueError("Not enough class-diverse expert labels for the baseline")
    # Ensure every retained class occurs in >= 2 separate groups.
    classes = sorted(set(y.tolist()))
    per_class_groups = {label: len(set(groups[y == label].tolist())) for label in classes}
    if min(per_class_groups.values()) < 2:
        raise ValueError("A class occurs in fewer than two independent groups")
    n_splits = min(3, min(per_class_groups.values()))
    folds = list(StratifiedGroupKFold(
        n_splits=n_splits, shuffle=True, random_state=43
    ).split(X, y, groups))
    labels = sorted(set(y.tolist()))
    results = []
    for name, factory in (
        ("most_frequent", lambda: DummyClassifier(strategy="most_frequent")),
        ("extra_trees", lambda: ExtraTreesClassifier(
            n_estimators=240, min_samples_leaf=2,
            max_features="sqrt", random_state=43, n_jobs=1,
            class_weight="balanced")),
    ):
        actual, predicted = [], []
        for train, test in folds:
            train_classes = set(y[train].tolist())
            # For rare classes, an unlucky grouped split may omit the class.
            # Report failure, do not pretend this is a valid CV.
            if train_classes != set(labels):
                raise ValueError("A grouped CV fold misses a training class")
            model = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                                  factory())
            model.fit(X[train], y[train])
            actual.extend(y[test].tolist())
            predicted.extend(model.predict(X[test]).tolist())
        score = {
            "model": name,
            "oof_macro_f1": round(float(f1_score(
                actual, predicted, labels=labels, average="macro",
                zero_division=0)), 4),
            "oof_accuracy": round(float(accuracy_score(actual, predicted)), 4),
            "per_class_recall": {
                label: round(float(sum(t == p == label for t, p in zip(actual, predicted)) /
                                   max(1, sum(t == label for t in actual))), 4)
                for label in labels
            },
        }
        results.append(score)
    return {
        "schema_version": 1,
        "purpose": "exploratory_offline_morphology_baseline",
        **info,
        "cv_folds": n_splits,
        "scores": results,
        "model_saved": False,
        "model_deployed": False,
        "test_set_independent": False,
        "warning": ("Reported out-of-fold scores are exploratory, not validated "
                    "generalization. Related acquisitions and cross-format "
                    "duplicates may remain unrecognized."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(json.dumps({"error": "label_database_missing"}))
        return 2
    try:
        report = experiment(get_scans(args.db))
    except (RuntimeError, ValueError) as error:
        print(json.dumps({"error": type(error).__name__,
                          "message": str(error), "model_saved": False}))
        return 3
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
