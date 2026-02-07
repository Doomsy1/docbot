"""Repo scanner -- walks the file tree and classifies source files."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import SourceFile

# Directories to skip unconditionally.
SKIP_DIRS: set[str] = {
    ".git", ".venv", "venv", "__pycache__", "dist", "build", ".tox", ".eggs",
    "node_modules", ".mypy_cache", ".pytest_cache",
    # Additional build / cache directories for other languages
    "target",          # Rust / Java (Maven)
    "bin", "obj",      # C# / Go binaries
    ".gradle",         # Gradle
    ".next", ".nuxt",  # Next.js / Nuxt
    "vendor",          # Go vendor, PHP
    "pkg",             # Go pkg
    ".cargo",          # Rust
    "Pods",            # iOS CocoaPods
    ".build",          # Swift
    "coverage",        # test coverage output
    ".cache",          # generic caches
}

# Language-aware entrypoint basenames.
ENTRYPOINT_NAMES: dict[str, str] = {
    # Python
    "main.py": "python",
    "app.py": "python",
    "server.py": "python",
    "cli.py": "python",
    "__main__.py": "python",
    "wsgi.py": "python",
    "asgi.py": "python",
    # Go
    "main.go": "go",
    # Rust
    "main.rs": "rust",
    "lib.rs": "rust",
    # Java / Kotlin
    "Main.java": "java",
    "Application.java": "java",
    "App.java": "java",
    "Main.kt": "kotlin",
    "Application.kt": "kotlin",
    # JavaScript / TypeScript
    "index.js": "javascript",
    "index.ts": "typescript",
    "index.tsx": "typescript",
    "server.js": "javascript",
    "server.ts": "typescript",
    "app.js": "javascript",
    "app.ts": "typescript",
    # Ruby
    "main.rb": "ruby",
    # C#
    "Program.cs": "csharp",
    # Swift
    "main.swift": "swift",
    # C/C++
    "main.c": "c",
    "main.cpp": "cpp",
}

# Files that signal a package / module root for each language.
PACKAGE_MARKERS: dict[str, str] = {
    "__init__.py": "python",
    "package.json": "javascript",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "kotlin",
    # .csproj matched via suffix check below

    "Package.swift": "swift",
    "Gemfile": "ruby",
}


# Extension → language name mapping for multi-language support.
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".swift": "swift",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
}


@dataclass
class ScanResult:
    """Collected information about a repository."""

    root: Path
    py_files: list[str] = field(default_factory=list)           # repo-relative paths (Python only, legacy)
    source_files: list[SourceFile] = field(default_factory=list) # all discovered source files
    packages: list[str] = field(default_factory=list)            # repo-relative dirs with __init__.py
    entrypoints: list[str] = field(default_factory=list)         # repo-relative paths
    languages: list[str] = field(default_factory=list)           # detected languages


def scan_repo(root: Path) -> ScanResult:
    """Walk *root* and return all source files, packages, and entrypoints.

    Paths are returned **relative to root** using forward slashes for
    portability.
    """
    from .models import SourceFile

    root = root.resolve()
    result = ScanResult(root=root)
    seen_packages: set[str] = set()
    seen_languages: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place so os.walk skips them.
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        rel_dir = Path(dirpath).resolve().relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            language = LANGUAGE_EXTENSIONS.get(ext)

            rel_path = f"{rel_dir}/{fname}" if rel_dir else fname

            # Track all recognised source files
            if language:
                result.source_files.append(SourceFile(path=rel_path, language=language))
                seen_languages.add(language)

            # Legacy: keep py_files populated for backward compatibility
            if ext == ".py":
                result.py_files.append(rel_path)

            # Package / module root detection (language-aware)
            # Handle suffix-based markers (e.g. .csproj files)
            if fname.endswith(".csproj"):
                pkg_dir = rel_dir if rel_dir else "."
                if pkg_dir not in seen_packages:
                    seen_packages.add(pkg_dir)
                    result.packages.append(pkg_dir)
            if fname in PACKAGE_MARKERS:
                pkg_lang = PACKAGE_MARKERS[fname]
                if pkg_lang == "python":
                    # Python packages are the directory containing __init__.py
                    if rel_dir and rel_dir not in seen_packages:
                        seen_packages.add(rel_dir)
                        result.packages.append(rel_dir)
                else:
                    # Other languages: the directory containing the marker is a package root
                    pkg_dir = rel_dir if rel_dir else "."
                    if pkg_dir not in seen_packages:
                        seen_packages.add(pkg_dir)
                        result.packages.append(pkg_dir)

            # Entrypoint detection (language-aware)
            if fname in ENTRYPOINT_NAMES:
                result.entrypoints.append(rel_path)

    result.py_files.sort()
    result.source_files.sort(key=lambda sf: sf.path)
    result.packages.sort()
    result.entrypoints.sort()
    result.languages = sorted(seen_languages)
    return result
