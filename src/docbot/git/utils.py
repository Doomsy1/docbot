"""Git helper utilities for docbot's git-integrated CLI.

Thin wrappers around git CLI commands via ``subprocess``.  All functions
accept a *repo_root* path so they can set ``cwd`` correctly, and all handle
errors gracefully (returning ``None`` or empty rather than raising).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_current_commit(repo_root: Path) -> str | None:
    """Return the HEAD commit hash, or ``None`` if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_changed_files(repo_root: Path, since_commit: str) -> list[str]:
    """Return repo-relative paths of files changed between *since_commit* and HEAD.

    Returns an empty list on any error.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{since_commit}..HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            paths = [
                p.replace("\\", "/")
                for p in result.stdout.strip().splitlines()
                if p.strip()
            ]
            return paths
    except Exception:
        pass
    return []


def is_commit_reachable(repo_root: Path, commit: str) -> bool:
    """Check whether *commit* still exists in the repository history."""
    try:
        result = subprocess.run(
            ["git", "cat-file", "-t", commit],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_repo_root(start: Path) -> Path | None:
    """Return the git repository root, or ``None`` if *start* is not inside a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None
