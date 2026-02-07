"""Repo scanner -- walks the file tree and classifies Python files."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Directories to skip unconditionally.
SKIP_DIRS: set[str] = {".git", ".venv", "venv", "__pycache__", "dist", "build", ".tox", ".eggs", "node_modules", ".mypy_cache", ".pytest_cache"}

# Basenames that signal an entrypoint.
ENTRYPOINT_NAMES: set[str] = {"main.py", "app.py", "server.py", "cli.py", "__main__.py", "wsgi.py", "asgi.py"}


@dataclass
class ScanResult:
    """Collected information about a Python repository."""

    root: Path
    py_files: list[str] = field(default_factory=list)       # repo-relative paths
    packages: list[str] = field(default_factory=list)        # repo-relative dirs with __init__.py
    entrypoints: list[str] = field(default_factory=list)     # repo-relative paths


def scan_repo(root: Path) -> ScanResult:
    """Walk *root* and return all Python files, packages, and entrypoints.

    Paths are returned **relative to root** using forward slashes for
    portability.
    """
    root = root.resolve()
    result = ScanResult(root=root)
    seen_packages: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place so os.walk skips them.
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        rel_dir = Path(dirpath).resolve().relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""

        for fname in filenames:
            if not fname.endswith(".py"):
                continue

            rel_path = f"{rel_dir}/{fname}" if rel_dir else fname
            result.py_files.append(rel_path)

            # Package detection
            if fname == "__init__.py" and rel_dir and rel_dir not in seen_packages:
                seen_packages.add(rel_dir)
                result.packages.append(rel_dir)

            # Entrypoint detection
            if fname in ENTRYPOINT_NAMES:
                result.entrypoints.append(rel_path)

    result.py_files.sort()
    result.packages.sort()
    result.entrypoints.sort()
    return result
