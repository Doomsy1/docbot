"""Tests for the repo scanner."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from docbot.scanner import (
    LANGUAGE_EXTENSIONS,
    SKIP_DIRS,
    ScanResult,
    scan_repo,
)


def _make_repo(structure: dict[str, str | dict]) -> Path:
    """Create a temporary directory with the given file structure.

    Structure is a dict where:
    - keys are file/dir names
    - values are file content strings or nested dicts for directories
    """
    root = Path(tempfile.mkdtemp())
    _populate(root, structure)
    return root


def _populate(base: Path, structure: dict) -> None:
    for name, content in structure.items():
        path = base / name
        if isinstance(content, dict):
            path.mkdir(parents=True, exist_ok=True)
            _populate(path, content)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


class TestLanguageDetection:
    def test_python_files(self):
        repo = _make_repo({"app.py": "print('hello')", "lib.py": "x = 1"})
        result = scan_repo(repo)
        assert "python" in result.languages
        assert len(result.source_files) == 2
        assert all(sf.language == "python" for sf in result.source_files)

    def test_typescript_files(self):
        repo = _make_repo({"app.ts": "const x = 1;", "types.tsx": "export type X = string;"})
        result = scan_repo(repo)
        assert "typescript" in result.languages

    def test_javascript_files(self):
        repo = _make_repo({"index.js": "module.exports = {};", "util.jsx": "export default function() {}"})
        result = scan_repo(repo)
        assert "javascript" in result.languages

    def test_go_files(self):
        repo = _make_repo({"main.go": "package main\nfunc main() {}"})
        result = scan_repo(repo)
        assert "go" in result.languages

    def test_rust_files(self):
        repo = _make_repo({"main.rs": "fn main() {}"})
        result = scan_repo(repo)
        assert "rust" in result.languages

    def test_java_files(self):
        repo = _make_repo({"App.java": "public class App {}"})
        result = scan_repo(repo)
        assert "java" in result.languages

    def test_mixed_language_repo(self):
        repo = _make_repo({
            "app.py": "x = 1",
            "index.ts": "const x = 1;",
            "main.go": "package main",
        })
        result = scan_repo(repo)
        assert "python" in result.languages
        assert "typescript" in result.languages
        assert "go" in result.languages
        assert len(result.source_files) == 3


class TestEntrypointDetection:
    def test_python_entrypoints(self):
        repo = _make_repo({"main.py": "", "app.py": "", "lib.py": ""})
        result = scan_repo(repo)
        assert "main.py" in result.entrypoints
        assert "app.py" in result.entrypoints
        assert "lib.py" not in result.entrypoints

    def test_js_entrypoints(self):
        repo = _make_repo({"index.js": "", "utils.js": ""})
        result = scan_repo(repo)
        assert "index.js" in result.entrypoints
        assert "utils.js" not in result.entrypoints

    def test_go_entrypoint(self):
        repo = _make_repo({"main.go": "package main"})
        result = scan_repo(repo)
        assert "main.go" in result.entrypoints

    def test_rust_entrypoints(self):
        repo = _make_repo({"main.rs": "", "lib.rs": ""})
        result = scan_repo(repo)
        assert "main.rs" in result.entrypoints
        assert "lib.rs" in result.entrypoints


class TestPackageDetection:
    def test_python_packages(self):
        repo = _make_repo({
            "src": {
                "mylib": {"__init__.py": "", "core.py": ""},
            }
        })
        result = scan_repo(repo)
        assert any("mylib" in pkg for pkg in result.packages)

    def test_js_package(self):
        repo = _make_repo({"package.json": '{"name": "test"}'})
        result = scan_repo(repo)
        assert len(result.packages) >= 1

    def test_cargo_toml(self):
        repo = _make_repo({"Cargo.toml": '[package]\nname = "test"'})
        result = scan_repo(repo)
        assert len(result.packages) >= 1


class TestSkipDirs:
    def test_node_modules_skipped(self):
        repo = _make_repo({
            "app.js": "const x = 1;",
            "node_modules": {"express": {"index.js": "module.exports = {};"}},
        })
        result = scan_repo(repo)
        paths = [sf.path for sf in result.source_files]
        assert not any("node_modules" in p for p in paths)
        assert len(result.source_files) == 1

    def test_git_dir_skipped(self):
        repo = _make_repo({
            "app.py": "x = 1",
            ".git": {"config": "stuff"},
        })
        result = scan_repo(repo)
        paths = [sf.path for sf in result.source_files]
        assert not any(".git" in p for p in paths)

    def test_pycache_skipped(self):
        repo = _make_repo({
            "app.py": "x = 1",
            "__pycache__": {"app.cpython-311.pyc": "binary"},
        })
        result = scan_repo(repo)
        paths = [sf.path for sf in result.source_files]
        assert not any("__pycache__" in p for p in paths)

    def test_target_dir_skipped(self):
        repo = _make_repo({
            "main.rs": "fn main() {}",
            "target": {"debug": {"main": "binary"}},
        })
        result = scan_repo(repo)
        paths = [sf.path for sf in result.source_files]
        assert not any("target" in p for p in paths)


class TestEdgeCases:
    def test_empty_repo(self):
        repo = _make_repo({})
        result = scan_repo(repo)
        assert result.source_files == []
        assert result.languages == []

    def test_no_recognized_extensions(self):
        repo = _make_repo({"data.csv": "a,b,c", "readme.txt": "hello"})
        result = scan_repo(repo)
        assert result.source_files == []

    def test_nested_structure(self):
        repo = _make_repo({
            "src": {
                "mylib": {
                    "__init__.py": "",
                    "core.py": "x = 1",
                    "utils.py": "y = 2",
                },
            }
        })
        result = scan_repo(repo)
        assert len(result.source_files) == 3
        paths = [sf.path for sf in result.source_files]
        assert any("core.py" in p for p in paths)

    def test_results_sorted(self):
        repo = _make_repo({"z.py": "", "a.py": "", "m.py": ""})
        result = scan_repo(repo)
        paths = [sf.path for sf in result.source_files]
        assert paths == sorted(paths)

    def test_languages_sorted(self):
        repo = _make_repo({"app.ts": "", "main.py": "", "lib.go": ""})
        result = scan_repo(repo)
        assert result.languages == sorted(result.languages)


class TestLanguageExtensions:
    def test_all_expected_extensions_present(self):
        expected = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".cs", ".swift", ".rb"}
        assert expected.issubset(set(LANGUAGE_EXTENSIONS.keys()))

    def test_skip_dirs_contains_common_dirs(self):
        expected = {"node_modules", "__pycache__", ".git", "target", "vendor", "dist"}
        assert expected.issubset(SKIP_DIRS)
