"""Conservative, *read-only* curation of private operator feedback.

This creates statistics about unique candidate training examples, not a
trained model or a dataset split. Conflicting or uncertain feedback is held
for explicit operator resolution. No raw files, IDs, filenames or written
operator evidence are included in the summary.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from afm_copilot.feedback import STORE_DIR, VERDICTS

_SCHEMA = 1


def curation_summary(directory: str | Path | None = None) -> dict:
    """Summarize distinct scans and block ambiguous labels from future training.

    Repeat confirmations of the same family count as one candidate. Any
    rejection, uncertainty, conflicting confirmed families or malformed
    record keeps the affected scan out of the confirmed candidate pool.
    There is deliberately no "latest wins" implicit relabeling.
    """
    root = Path(directory) if directory else STORE_DIR
    ledger = root / "operator_feedback.jsonl"
    empty = {
        "schema_version": _SCHEMA, "events": 0, "unique_scans": 0,
        "candidate_scans": 0, "needs_resolution": 0,
        "no_positive_label": 0, "repeated_confirmations": 0,
        "confirmed_families": {}, "model_updated": False,
        "training_data_exported": False,
    }
    if not ledger.is_file():
        return empty

    by_id = defaultdict(list)
    for n, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Empty feedback record at line {n}")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in feedback at line {n}") from exc
        if not isinstance(record, dict) or record.get("schema_version") != _SCHEMA:
            raise ValueError(f"Unsupported feedback record at line {n}")
        scan_id = record.get("scan_id")
        if not isinstance(scan_id, str) or len(scan_id) != 64 or any(
            c not in "0123456789abcdef" for c in scan_id
        ):
            raise ValueError(f"Invalid anonymous scan ID at line {n}")
        verdict = record.get("verdict")
        if verdict not in VERDICTS:
            raise ValueError(f"Invalid feedback verdict at line {n}")
        if record.get("origin") != "explicit-operator-feedback":
            raise ValueError(f"Unverified feedback origin at line {n}")
        if record.get("model_updated") is not False:
            raise ValueError(f"Unexpected model state at line {n}")
        if verdict == "confirmed" and (
            record.get("validated_label") != record.get("family_reviewed")
            or record.get("training_eligible") is not True
        ):
            raise ValueError(f"Invalid confirmed label at line {n}")
        by_id[scan_id].append(record)

    candidates = Counter()
    needs_resolution = 0
    no_positive = 0
    repeats = 0
    for group in by_id.values():
        labels = {event["validated_label"] for event in group
                  if event["verdict"] == "confirmed"}
        held = any(event["verdict"] != "confirmed" for event in group)
        if held or len(labels) > 1:
            needs_resolution += 1
        elif len(labels) == 0:
            no_positive += 1
        else:
            label = next(iter(labels))
            if not isinstance(label, str) or not label:
                raise ValueError("Invalid empty family in confirmed feedback")
            candidates[label] += 1
            repeats += len(group) - 1

    return {
        **empty, "events": sum(map(len, by_id.values())),
        "unique_scans": len(by_id), "candidate_scans": sum(candidates.values()),
        "needs_resolution": needs_resolution, "no_positive_label": no_positive,
        "repeated_confirmations": repeats,
        "confirmed_families": dict(sorted(candidates.items())),
    }


def main() -> int:
    """Print only safe aggregates; never export a trainable manifest."""
    print(json.dumps(curation_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
