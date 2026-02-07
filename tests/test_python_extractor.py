"""Tests for the Python AST extractor."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from docbot.extractors.python_extractor import PythonExtractor


@pytest.fixture
def extractor() -> PythonExtractor:
    return PythonExtractor()


def _write_tmp(code: str, suffix: str = ".py") -> Path:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8")
    f.write(code)
    f.close()
    return Path(f.name)


class TestFunctionExtraction:
    def test_simple_function(self, extractor: PythonExtractor):
        path = _write_tmp('def hello(name: str) -> str:\n    """Say hello."""\n    return f"Hello {name}"')
        result = extractor.extract_file(path, "mod.py", "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "hello"
        assert sym.kind == "function"
        assert "hello" in sym.signature
        assert sym.docstring_first_line == "Say hello."
        assert sym.citation.file == "mod.py"
        assert sym.citation.line_start == 1

    def test_async_function(self, extractor: PythonExtractor):
        path = _write_tmp("async def fetch(url: str) -> bytes:\n    pass")
        result = extractor.extract_file(path, "mod.py", "python")
        assert len(result.symbols) == 1
        assert "async def" in result.symbols[0].signature

    def test_private_functions_excluded(self, extractor: PythonExtractor):
        path = _write_tmp("def _private():\n    pass\n\ndef public():\n    pass")
        result = extractor.extract_file(path, "mod.py", "python")
        names = [s.name for s in result.symbols]
        assert "public" in names
        assert "_private" not in names


class TestClassExtraction:
    def test_simple_class(self, extractor: PythonExtractor):
        path = _write_tmp('class MyClass:\n    """A class."""\n    pass')
        result = extractor.extract_file(path, "mod.py", "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "MyClass"
        assert sym.kind == "class"
        assert "MyClass" in sym.signature
        assert sym.docstring_first_line == "A class."

    def test_class_with_bases(self, extractor: PythonExtractor):
        path = _write_tmp("class Child(Parent, Mixin):\n    pass")
        result = extractor.extract_file(path, "mod.py", "python")
        assert "Parent" in result.symbols[0].signature
        assert "Mixin" in result.symbols[0].signature

    def test_private_class_excluded(self, extractor: PythonExtractor):
        path = _write_tmp("class _Internal:\n    pass\n\nclass Public:\n    pass")
        result = extractor.extract_file(path, "mod.py", "python")
        names = [s.name for s in result.symbols]
        assert "Public" in names
        assert "_Internal" not in names


class TestImportExtraction:
    def test_absolute_import(self, extractor: PythonExtractor):
        path = _write_tmp("import os\nimport sys")
        result = extractor.extract_file(path, "mod.py", "python")
        assert "os" in result.imports
        assert "sys" in result.imports

    def test_from_import(self, extractor: PythonExtractor):
        path = _write_tmp("from pathlib import Path")
        result = extractor.extract_file(path, "mod.py", "python")
        assert "pathlib" in result.imports

    def test_relative_import(self, extractor: PythonExtractor):
        path = _write_tmp("from . import utils\nfrom ..models import User")
        result = extractor.extract_file(path, "src/pkg/mod.py", "python")
        assert len(result.imports) >= 1


class TestEnvVarExtraction:
    def test_os_getenv(self, extractor: PythonExtractor):
        path = _write_tmp('import os\nkey = os.getenv("API_KEY")')
        result = extractor.extract_file(path, "mod.py", "python")
        assert len(result.env_vars) == 1
        assert result.env_vars[0].name == "API_KEY"

    def test_os_environ_get(self, extractor: PythonExtractor):
        path = _write_tmp('import os\nkey = os.environ.get("SECRET", "default")')
        result = extractor.extract_file(path, "mod.py", "python")
        assert len(result.env_vars) == 1
        assert result.env_vars[0].name == "SECRET"
        assert result.env_vars[0].default == "default"


class TestRaisedErrorExtraction:
    def test_raise_statement(self, extractor: PythonExtractor):
        path = _write_tmp('def fail():\n    raise ValueError("bad input")')
        result = extractor.extract_file(path, "mod.py", "python")
        assert len(result.raised_errors) == 1
        assert "ValueError" in result.raised_errors[0].expression

    def test_bare_raise(self, extractor: PythonExtractor):
        path = _write_tmp("def reraise():\n    try:\n        pass\n    except:\n        raise")
        result = extractor.extract_file(path, "mod.py", "python")
        assert len(result.raised_errors) == 1
        assert "bare raise" in result.raised_errors[0].expression


class TestEdgeCases:
    def test_syntax_error_file(self, extractor: PythonExtractor):
        path = _write_tmp("def broken(\n")
        result = extractor.extract_file(path, "bad.py", "python")
        # Should not crash, returns partial result.
        assert result is not None

    def test_empty_file(self, extractor: PythonExtractor):
        path = _write_tmp("")
        result = extractor.extract_file(path, "empty.py", "python")
        assert result.symbols == []
        assert result.imports == []

    def test_citations_populated(self, extractor: PythonExtractor):
        path = _write_tmp("def foo():\n    pass\n\nclass Bar:\n    pass")
        result = extractor.extract_file(path, "mod.py", "python")
        assert len(result.citations) == 2
        for cit in result.citations:
            assert cit.file == "mod.py"
            assert cit.line_start >= 1
