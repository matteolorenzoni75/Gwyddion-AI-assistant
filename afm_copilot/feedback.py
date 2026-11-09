"""Private, operator-confirmed feedback. No automatic retraining or processing.

Every feedback event is append-only and stored outside the public checkout.
IDs use a private HMAC key over the scan bytes; no filenames or raw data enter
any shareable training report. Only explicitly confirmed examples are eligible
for a future, separate training process.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = Path.home() / "AFM_Copilot_Private_Audits" / "learning_feedback"
VERDICTS = frozenset({"confirmed", "rejected", "uncertain"})
BLOCKED_PATH_PARTS = frozenset({"blind", "blind_test", "blind-test", "holdout", "test_set", "test-set"})
ANONYMOUS_STEM = re.compile(r"scan-\d{3,}$", re.I)


def _private_store(directory: Path) -> Path:
    directory = directory.expanduser().resolve()
    if directory == PROJECT_ROOT or PROJECT_ROOT in directory.parents:
        raise ValueError("Feedback must be outside the Git checkout")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _key(directory: Path) -> bytes:
    path = directory / ".private_hmac_key"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        key = path.read_bytes()
        if len(key) != 32:
            raise ValueError("Private feedback key is damaged; refusing to assign IDs")
        return key
    key = secrets.token_bytes(32)
    with os.fdopen(fd, "wb") as stream:
        stream.write(key)
    return key


def _is_holdout(path: Path) -> bool:
    lowered = {part.lower().replace(" ", "_") for part in path.parts}
    export_root = PROJECT_ROOT / "export"
    return (export_root == path or export_root in path.parents or
            bool(lowered & BLOCKED_PATH_PARTS) or
            any(part.startswith("blind_test") or part.startswith("holdout") for part in lowered) or
            bool(ANONYMOUS_STEM.fullmatch(path.stem)))


def record_feedback(
    scan: str | Path,
    *,
    family: str,
    effect: str,
    verdict: str,
    evidence: Sequence[str],
    confirmed_training: bool = False,
    directory: str | Path | None = None,
) -> dict:
    """Record one operator decision; refuse implicit training labels.

    The GUI must explicitly confirm that the scan belongs to the training
    pool (not the blind evaluation set). The routine never alters the scan,
    changes a recipe or fits/updates a model.
    """
    from afm_copilot.morphology import EFFECTS, FAMILIES

    scan = Path(scan).expanduser().resolve()
    if not scan.is_file():
        raise FileNotFoundError("The source scan is unavailable")
    if not confirmed_training:
        raise ValueError("Operator must explicitly confirm training-set membership")
    if _is_holdout(scan):
        raise ValueError("Blind/test scans cannot be used as learning labels")
    if family not in FAMILIES or effect not in EFFECTS or verdict not in VERDICTS:
        raise ValueError("Unknown morphology family, effect or feedback verdict")
    if isinstance(evidence, (str, bytes)):
        raise ValueError("Evidence must be a sequence of observations")
    if any(not isinstance(s, str) or len(s) > 500 for s in evidence):
        raise ValueError("Invalid evidence content")
    observations = [s.strip() for s in evidence if s.strip()]
    if verdict == "confirmed" and (family == "uncertain" or not observations):
        raise ValueError("Confirmed training labels require a definite family and evidence")

    out = _private_store(Path(directory) if directory else STORE_DIR)
    digest = hashlib.sha256()
    with scan.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    private_id = hmac.new(_key(out), digest.digest(), hashlib.sha256).hexdigest()
    row = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scan_id": private_id,
        "file_format": scan.suffix.lower(),
        "family_reviewed": family,
        "effect": effect,
        "verdict": verdict,
        "validated_label": family if verdict == "confirmed" else None,
        "training_eligible": verdict == "confirmed",
        "evidence": observations,
        "origin": "explicit-operator-feedback",
        "model_updated": False,
    }
    # The public/shareable ledger never exposes filenames or paths. A separate
    # PRIVATE source index is needed to find the approved source again when
    # curating future datasets. It lives beside the private key, outside Git.
    # Index first: an orphaned path entry is harmless, whereas a feedback event
    # without a retrievable source would be silently unusable for training.
    source_entry = json.dumps({
        "schema_version": 1, "scan_id": private_id,
        "path": str(scan), "file_size": scan.stat().st_size,
        "recorded_at": row["recorded_at"],
    }, ensure_ascii=False, allow_nan=False) + "\n"
    fd = os.open(str(out / "private_source_index.jsonl"),
                 os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(source_entry)

    line = json.dumps(row, allow_nan=False, ensure_ascii=False) + "\n"
    fd = os.open(str(out / "operator_feedback.jsonl"),
                 os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(line)
    return {"scan_id": private_id, "verdict": verdict,
            "training_eligible": row["training_eligible"], "store": str(out)}


def feedback_counts(directory: str | Path | None = None) -> dict[str, int]:
    """Aggregate counts only; never publish scan IDs or evidence."""
    path = Path(directory) if directory else STORE_DIR
    result = {"total_reviews": 0, "confirmed": 0, "rejected": 0, "uncertain": 0}
    file = path / "operator_feedback.jsonl"
    if not file.is_file():
        return result
    for line in file.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        verdict = record.get("verdict")
        if verdict not in VERDICTS:
            raise ValueError("Invalid feedback record")
        result["total_reviews"] += 1
        result[verdict] += 1
    return result
