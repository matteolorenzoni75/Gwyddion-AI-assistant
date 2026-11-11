"""Local maintenance: never touch raw scans, labels or private archives.

No destructive git clean, hard reset, force push, automatic staging or merges.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from afm_copilot.feedback import PROJECT_ROOT

SAFE_CACHES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"})
BRANCH = "dev/image-wizard"


def candidates(root: Path = PROJECT_ROOT) -> list[Path]:
    root = root.resolve()
    found = []
    for p in root.rglob("*"):
        if not p.is_dir() or p.name not in SAFE_CACHES:
            continue
        parts = p.relative_to(root).parts
        if any(x in (".git", ".venv", "out", "data", "export") for x in parts):
            continue
        if p.is_symlink():
            continue
        found.append(p)
    return sorted(found, key=lambda p: (len(p.parts), str(p)), reverse=True)


def tidy(*, apply=False, root: Path = PROJECT_ROOT) -> dict:
    root = root.resolve()
    found = candidates(root)
    removed = 0
    if apply:
        for folder in found:
            if not folder.is_dir():
                continue
            canonical = folder.resolve()
            if root not in canonical.parents:
                raise ValueError("Cache escaped project directory")
            shutil.rmtree(folder)
            removed += 1
    return {
        "mode": "apply_safe_caches" if apply else "preview",
        "safe_cache_directories": len(found), "safe_cache_directories_removed": removed,
        "raw_files_touched": 0, "private_labels_touched": 0,
        "tracked_repository_files_deleted": 0,
    }


def _git(*args) -> str:
    return subprocess.check_output(["git", *args], cwd=PROJECT_ROOT,
                                   text=True, stderr=subprocess.STDOUT).strip()


def git_status() -> dict:
    try:
        branch = _git("branch", "--show-current")
        dirty = bool(_git("status", "--porcelain", "--untracked-files=normal"))
        tracking = _git("remote", "get-url", "origin")
        return {"branch": branch, "worktree_dirty": dirty,
                "origin_configured": bool(tracking),
                "allowed_push_branch": BRANCH, "main_unchanged": True}
    except (OSError, subprocess.CalledProcessError):
        return {"error": "git_status_unavailable"}


def push_reviewed() -> dict:
    state = git_status()
    if state.get("branch") != BRANCH:
        return {"status": "blocked", "reason": "not_on_dev_branch", **state}
    if state.get("worktree_dirty"):
        return {"status": "blocked", "reason": "uncommitted_or_untracked_changes",
                "advice": "Review and explicitly commit source files, never private scans",
                **state}
    try:
        subprocess.run(["git", "diff", "--check"], cwd=PROJECT_ROOT, check=True,
                       capture_output=True, text=True)
        result = subprocess.run(["git", "push", "origin", BRANCH],
                                cwd=PROJECT_ROOT, capture_output=True, text=True)
        return {"status": "pushed" if result.returncode == 0 else "failed",
                "exit_code": result.returncode,
                "note": "Only existing commits were pushed; no staging, commit or merge.",
                **state}
    except (OSError, subprocess.CalledProcessError):
        return {"status": "failed", "reason": "git_not_available_or_diff_check_failed",
                **state}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "clean-preview", "clean-safe", "push"))
    args = parser.parse_args(argv)
    if args.action == "status":
        report = git_status()
    elif args.action == "clean-preview":
        report = tidy()
    elif args.action == "clean-safe":
        report = tidy(apply=True)
    else:
        report = push_reviewed()
    print(json.dumps(report, indent=2))
    return 1 if report.get("status") in ("blocked", "failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
