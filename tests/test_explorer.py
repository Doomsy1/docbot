"""Tests for the explorer module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from docbot.extractors import setup_extractors
from docbot.pipeline.explorer import explore_scope
from docbot.models import ScopePlan


def _make_repo(structure: dict[str, str | dict]) -> Path:
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


@pytest.fixture(autouse=True)
def _setup():
    """Register extractors before each test."""
    setup_extractors(llm_client=None)
    yield


class TestExploreScope:
    def test_python_scope(self):
        repo = _make_repo({
            "src": {
                "pkg": {
                    "__init__.py": "",
                    "core.py": 'import os\n\ndef hello(name: str) -> str:\n    """Say hello."""\n    return f"Hello {name}"',
                }
            }
        })
        plan = ScopePlan(
            scope_id="pkg",
            title="Package",
            paths=["src/pkg/__init__.py", "src/pkg/core.py"],
        )
        result = explore_scope(plan, repo)
        assert result.scope_id == "pkg"
        assert result.error is None
        assert "python" in result.languages
        names = [s.name for s in result.public_api]
        assert "hello" in names

    def test_typescript_scope(self):
        repo = _make_repo({
            "src": {
                "app.ts": "export function createApp(): void {}\nexport class Server {}",
            }
        })
        plan = ScopePlan(
            scope_id="app",
            title="App",
            paths=["src/app.ts"],
        )
        result = explore_scope(plan, repo)
        assert result.error is None
        assert "typescript" in result.languages
        names = [s.name for s in result.public_api]
        assert "createApp" in names

    def test_go_scope(self):
        repo = _make_repo({
            "main.go": 'package main\n\nimport "fmt"\n\nfunc Hello(name string) string {\n\treturn fmt.Sprintf("Hello %s", name)\n}',
        })
        plan = ScopePlan(
            scope_id="main",
            title="Main",
            paths=["main.go"],
        )
        result = explore_scope(plan, repo)
        assert result.error is None
        assert "go" in result.languages
        names = [s.name for s in result.public_api]
        assert "Hello" in names

    def test_mixed_language_scope(self):
        repo = _make_repo({
            "app.py": "def foo():\n    pass",
            "index.ts": "export function bar(): void {}",
        })
        plan = ScopePlan(
            scope_id="mixed",
            title="Mixed",
            paths=["app.py", "index.ts"],
        )
        result = explore_scope(plan, repo)
        assert result.error is None
        assert "python" in result.languages
        assert "typescript" in result.languages
        names = [s.name for s in result.public_api]
        assert "foo" in names
        assert "bar" in names

    def test_missing_file_skipped(self):
        repo = _make_repo({"app.py": "def foo():\n    pass"})
        plan = ScopePlan(
            scope_id="test",
            title="Test",
            paths=["app.py", "nonexistent.py"],
        )
        result = explore_scope(plan, repo)
        assert result.error is None
        names = [s.name for s in result.public_api]
        assert "foo" in names

    def test_unsupported_language_file(self):
        repo = _make_repo({
            "data.csv": "a,b,c\n1,2,3",
            "app.py": "def hello():\n    pass",
        })
        plan = ScopePlan(
            scope_id="test",
            title="Test",
            paths=["data.csv", "app.py"],
        )
        result = explore_scope(plan, repo)
        assert result.error is None
        # CSV file should appear as a citation with a note.
        csv_cits = [c for c in result.citations if "data.csv" in c.file and c.snippet and "No extractor" in c.snippet]
        assert len(csv_cits) == 1

    def test_key_files_detected(self):
        repo = _make_repo({
            "__init__.py": "",
            "cli.py": "def main():\n    pass",
            "utils.py": "def helper():\n    pass",
        })
        plan = ScopePlan(
            scope_id="pkg",
            title="Package",
            paths=["__init__.py", "cli.py", "utils.py"],
        )
        result = explore_scope(plan, repo)
        assert "__init__.py" in result.key_files
        assert "cli.py" in result.key_files

    def test_entrypoints_detected(self):
        repo = _make_repo({
            "main.py": "def main():\n    pass",
            "lib.py": "x = 1",
        })
        plan = ScopePlan(
            scope_id="pkg",
            title="Package",
            paths=["main.py", "lib.py"],
        )
        result = explore_scope(plan, repo)
        assert "main.py" in result.entrypoints

    def test_imports_collected(self):
        repo = _make_repo({
            "app.py": "import os\nimport json\nfrom pathlib import Path",
        })
        plan = ScopePlan(
            scope_id="test",
            title="Test",
            paths=["app.py"],
        )
        result = explore_scope(plan, repo)
        assert "os" in result.imports
        assert "json" in result.imports

    def test_env_vars_collected(self):
        repo = _make_repo({
            "config.py": 'import os\nkey = os.getenv("SECRET_KEY")',
        })
        plan = ScopePlan(
            scope_id="test",
            title="Test",
            paths=["config.py"],
        )
        result = explore_scope(plan, repo)
        assert len(result.env_vars) == 1
        assert result.env_vars[0].name == "SECRET_KEY"

    def test_summary_generated(self):
        repo = _make_repo({
            "app.py": "def hello():\n    pass\n\nclass Server:\n    pass",
        })
        plan = ScopePlan(
            scope_id="test",
            title="Test",
            paths=["app.py"],
        )
        result = explore_scope(plan, repo)
        # Without LLM, a basic template summary is generated.
        assert result.summary
        assert "Test" in result.summary

    def test_empty_scope(self):
        repo = _make_repo({})
        plan = ScopePlan(
            scope_id="empty",
            title="Empty",
            paths=[],
        )
        result = explore_scope(plan, repo)
        assert result.error is None
        assert result.public_api == []
