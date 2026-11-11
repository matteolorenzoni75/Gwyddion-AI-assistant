"""Read-only AFM dataset deduplication and trace/retrace pairing.

Original files and operator labels are never deleted or edited.
Exact copies are collapsed into one training candidate; channel directions
are considered separate only when there is evidence for different data.
Names alone NEVER prove that two images are the same acquisition.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from afm_copilot.labeling import DEFAULT_DB, get_scans

# Accept explicit suffixes only; prevent accidental matching of e.g.
# "retracement" and arbitrary words inside specimen names.
_DIRECTION = re.compile(
    r"^(?P<base>.*?)(?:[\s_.\-(]+)"
    r"(?P<direction>retrace|trace|backward|forward|reverse|"
    r"traceback|traceforward)[\s_.\-)0-9]*$", re.I)
_MAP = {
    "trace": "trace", "forward": "trace", "traceforward": "trace",
    "retrace": "retrace", "backward": "retrace", "reverse": "retrace",
    "traceback": "retrace",
}
_EXCLUDED_QUALITY = frozenset({"reject", "review"})
_EXCLUDED_FAMILY = frozenset({"unclassified", "uncertain", None})


def _direction(path: str) -> tuple[str, str] | None:
    stem = Path(path).stem
    match = _DIRECTION.match(stem)
    if not match or not match["base"].strip(" ._-("):
        return None
    return (match["base"].strip(" ._-(").casefold(),
            _MAP[match["direction"].casefold()])


def _rank(row: dict) -> tuple:
    """Prefer a usable, labeled, evidence-rich record; stable tie by ID."""
    return (
        row.get("family") not in _EXCLUDED_FAMILY,
        row.get("quality") not in _EXCLUDED_QUALITY,
        row.get("quality") == "usable",
        len(row.get("metrics") or {}),
        int(row.get("confidence") or 0),
        -int(row["scan_id"]),
    )


def plan_rows(rows: list[dict]) -> dict:
    """Return safe aggregate stats plus private selection IDs for local use.

    Only trust a saved SHA-256 on a *labeled* record; never use filenames as
    identity. Missing SHA records remain separate until verified.
    """
    labeled = [r for r in rows if r.get("family") not in (None, "unclassified")]
    identities: dict[str, list[dict]] = defaultdict(list)
    for row in labeled:
        digest = row.get("sha256")
        identity = "sha:" + digest if digest and len(digest) == 64 else "id:" + str(row["scan_id"])
        identities[identity].append(row)

    chosen = []
    suppressed = []
    conflicts = []
    group_details = []
    for members in identities.values():
        if len(members) == 1:
            chosen.append(members[0])
            continue
        labels = {r.get("family") for r in members}
        if len(labels) != 1:
            # Human contradictions must be resolved, not silently overwritten.
            conflicts.extend(r["scan_id"] for r in members)
            group_details.append({"type": "conflicting_labels", "count": len(members)})
            continue
        best = max(members, key=_rank)
        chosen.append(best)
        suppressed.extend(r["scan_id"] for r in members if r["scan_id"] != best["scan_id"])
        group_details.append({"type": "exact_copy", "count": len(members)})

    # Warn about trace/retrace pairs among DISTINCT byte identities only.
    by_pair = defaultdict(dict)
    for r in chosen:
        direction = _direction(r["path"])
        if direction:
            base, side = direction
            key = (str(Path(r["path"]).parent).casefold(), base)
            by_pair[key].setdefault(side, []).append(r)
    pairs = []
    for directions in by_pair.values():
        if "trace" not in directions or "retrace" not in directions:
            continue
        for trace in directions["trace"]:
            for retrace in directions["retrace"]:
                if trace.get("sha256") and trace["sha256"] == retrace.get("sha256"):
                    continue
                pairs.append((trace["scan_id"], retrace["scan_id"]))

    candidate = [
        r for r in chosen if r.get("family") not in _EXCLUDED_FAMILY
        and r.get("quality") not in _EXCLUDED_QUALITY
    ]
    families = Counter(r["family"] for r in candidate)
    return {
        "registered_labeled": len(labeled),
        "exact_duplicates_excluded": len(suppressed),
        "exact_duplicate_groups": sum(x["type"] == "exact_copy" for x in group_details),
        "conflicting_exact_copy_groups": sum(x["type"] == "conflicting_labels" for x in group_details),
        "conflicting_rows_held": len(conflicts),
        "distinct_labeled_after_exact_dedup": len(chosen),
        "eligible_unique_labeled": len(candidate),
        "quality_or_uncertain_excluded": len(chosen) - len(candidate),
        "potential_trace_retrace_pairs_by_name": len(pairs),
        "candidate_family_counts": dict(sorted(families.items())),
        "model_trained": False,
        "dedup_method": "exact_sha256_only",
        "note": ("Trace/retrace count is a filename-based candidate pairing, "
                 "not channel-level verification; distinct files are retained. "
                 "Cross-format or visually similar acquisitions need further review."),
        # Never serialize these private IDs to shareable stdout.
        "_private_selection": {
            "candidate_ids": sorted(r["scan_id"] for r in candidate),
            "exact_duplicate_ids": sorted(suppressed),
            "conflict_ids": sorted(conflicts),
            "possible_trace_retrace_pairs": pairs,
        },
    }


def safe_report(rows: list[dict]) -> dict:
    """Aggregate JSON only: no names, IDs, free-text labels or hashes."""
    return {k: v for k, v in plan_rows(rows).items()
            if not k.startswith("_private_")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(json.dumps({"error": "private_label_database_not_found"}))
        return 2
    print(json.dumps(safe_report(get_scans(args.db)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
