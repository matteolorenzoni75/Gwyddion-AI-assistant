"""Read-only, privacy-safe readiness audit of expert AFM labels.

Run: python -B -m afm_copilot.learning_audit
Stdout reports ONLY aggregate counts. It never exports SQLite, paths,
sample/group IDs, image content, operator notes or identifying hashes.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from afm_copilot.labeling import DEFAULT_DB, FAMILIES, ROLES, get_scans

# Fixed numeric, morphology-oriented features. No file paths, sample IDs,
# operator text, instrument filenames, or human-selected artifact labels.
FEATURES = (
    "tilt", "row_banding", "row_step_fraction",
    "object_fraction", "raised_fraction", "sunken_fraction",
    "object_count", "object_median_size", "object_size_spread",
    "object_elongation", "periodicity", "period_confirmed",
    "correlation_length", "skewness", "kurtosis",
    "bimodality", "rms", "scan_size", "pixel_size",
)
EXCLUDED = frozenset({"unclassified", "uncertain"})


def _scalar(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def audit_rows(rows: list[dict]) -> dict:
    """Aggregate labels, feature coverage, split integrity and blockers."""
    labeled = [r for r in rows if r.get("family") in FAMILIES
               and r.get("family") != "unclassified"]
    eligible = [r for r in labeled if r["family"] not in EXCLUDED
                and r.get("quality") not in ("reject", "review")]
    counts = Counter(r["family"] for r in labeled)
    roles = Counter(r.get("dataset_role") or "unassigned" for r in labeled)
    qualities = Counter(r.get("quality") or "unknown" for r in labeled)
    groups = defaultdict(set)
    hashes = defaultdict(set)
    missing_group = 0
    for r in eligible:
        role = r.get("dataset_role") or "unassigned"
        group = (r.get("sample_group") or "").strip()
        if not group:
            missing_group += 1
        elif role != "unassigned":
            groups[group].add(role)
        if r.get("sha256") and role != "unassigned":
            hashes[r["sha256"]].add(role)

    described = [r for r in eligible if
                 sum(_scalar((r.get("metrics") or {}).get(k)) for k in FEATURES) >= 5]
    missing = {k: sum(not _scalar((r.get("metrics") or {}).get(k))
                      for r in eligible) for k in FEATURES}
    groups_by_role = {role: len({
        (r.get("sample_group") or "").strip() for r in eligible
        if r.get("dataset_role") == role and (r.get("sample_group") or "").strip()
    }) for role in ROLES}
    families_by_role = {role: dict(sorted(Counter(
        r["family"] for r in eligible if r.get("dataset_role") == role
    ).items())) for role in ROLES}

    blockers = []
    if not labeled:
        blockers.append("no_labels")
    if missing_group:
        blockers.append("eligible_scans_without_specimen_group")
    if any(len(parts) > 1 for parts in groups.values()):
        blockers.append("specimen_group_crosses_splits")
    if any(len(parts) > 1 for parts in hashes.values()):
        blockers.append("identical_content_crosses_splits")
    if len(described) < 30:
        blockers.append("fewer_than_30_scans_with_5_numeric_descriptors")
    training = families_by_role["train"]
    validation = families_by_role["validation"]
    if len(training) < 2 or len(validation) < 2:
        blockers.append("need_two_families_in_train_and_validation")
    if groups_by_role["train"] < 3 or groups_by_role["validation"] < 2:
        blockers.append("insufficient_independent_specimen_groups")
    # Presence of explicit holdout is mandatory for a future final score.
    if groups_by_role["holdout"] < 2:
        blockers.append("reserve_independent_holdout_groups")
    return {
        "schema_version": 1,
        "total_registered": len(rows),
        "labeled": len(labeled),
        "unlabeled": len(rows) - len(labeled),
        "morphology_counts": dict(sorted(counts.items())),
        "quality_counts": dict(sorted(qualities.items())),
        "partition_counts": dict(sorted(roles.items())),
        "eligible_for_future_training_review": len(eligible),
        "with_at_least_5_numeric_descriptors": len(described),
        "missing_numeric_feature_counts": missing,
        "specimen_groups_per_partition": groups_by_role,
        "morphology_per_partition": families_by_role,
        "cross_partition_specimen_groups": sum(len(x) > 1 for x in groups.values()),
        "cross_partition_identical_bytes": sum(len(x) > 1 for x in hashes.values()),
        "eligible_scans_missing_specimen_group": missing_group,
        "blockers": blockers,
        "training_ready": not blockers,
        "model_trained": False,
        "contains_raw_data": False,
        "warning": ("Counts describe operator labels, not measured ML accuracy. "
                    "No model is trained, no raw scan or private identifier exported."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="Private label database (never uploaded)")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(json.dumps({"error": "private_label_database_not_found",
                          "model_trained": False}))
        return 2
    report = audit_rows(get_scans(args.db))
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
