"""Tests for the LLM fallback extractor."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from docbot.extractors.llm_extractor import LLMExtractor


class FakeLLMClient:
    """Minimal fake that mimics LLMClient for testing."""

    def __init__(self, response: str = "{}"):
        self._response = response
        self.ask = AsyncMock(return_value=response)

    async def chat(self, messages, *, json_mode=False):
        return self._response


def _write_tmp(code: str, suffix: str = ".rb") -> Path:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8")
    f.write(code)
    f.close()
    return Path(f.name)


class TestParseResponse:
    """Test the JSON response parser directly."""

    def test_valid_json(self):
        raw = json.dumps({
            "symbols": [
                {"name": "greet", "kind": "function", "signature": "def greet(name)", "line": 1}
            ],
            "imports": ["json", "os"],
            "env_vars": [{"name": "API_KEY", "line": 5}],
            "errors": [{"expression": "raise RuntimeError", "line": 10}],
        })
        result = LLMExtractor._parse_response(raw, "test.rb")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "greet"
        assert result.symbols[0].kind == "function"
        assert "json" in result.imports
        assert "os" in result.imports
        assert len(result.env_vars) == 1
        assert result.env_vars[0].name == "API_KEY"
        assert len(result.raised_errors) == 1

    def test_json_with_markdown_fences(self):
        raw = '```json\n{"symbols": [{"name": "foo", "kind": "function", "signature": "foo()", "line": 1}], "imports": [], "env_vars": [], "errors": []}\n```'
        result = LLMExtractor._parse_response(raw, "test.rb")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "foo"

    def test_invalid_json_returns_empty(self):
        result = LLMExtractor._parse_response("not json at all", "test.rb")
        assert result.symbols == []
        assert result.imports == []

    def test_empty_json_object(self):
        result = LLMExtractor._parse_response("{}", "test.rb")
        assert result.symbols == []
        assert result.imports == []

    def test_symbols_without_name_skipped(self):
        raw = json.dumps({
            "symbols": [
                {"name": "", "kind": "function", "signature": "", "line": 1},
                {"name": "valid", "kind": "function", "signature": "valid()", "line": 2},
            ],
            "imports": [],
            "env_vars": [],
            "errors": [],
        })
        result = LLMExtractor._parse_response(raw, "test.rb")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "valid"

    def test_citations_populated(self):
        raw = json.dumps({
            "symbols": [
                {"name": "foo", "kind": "function", "signature": "foo()", "line": 5}
            ],
            "imports": [],
            "env_vars": [],
            "errors": [],
        })
        result = LLMExtractor._parse_response(raw, "app.rb")
        assert len(result.citations) == 1
        assert result.citations[0].file == "app.rb"
        assert result.citations[0].line_start == 5


class TestExtractFile:
    """Test the full extract_file flow with a mock LLM."""

    def test_successful_extraction(self):
        response = json.dumps({
            "symbols": [{"name": "greet", "kind": "function", "signature": "def greet(name)", "line": 1}],
            "imports": ["json"],
            "env_vars": [],
            "errors": [],
        })
        # Patch LLMClient type check.
        from docbot.llm import LLMClient as RealClient
        fake = FakeLLMClient(response)
        # Create the extractor by faking the isinstance check.
        ext = LLMExtractor.__new__(LLMExtractor)
        ext._client = fake

        path = _write_tmp("def greet(name)\n  puts name\nend")
        result = ext.extract_file(path, "app.rb", "ruby")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "greet"

    def test_truncation_for_large_files(self):
        # Create a file larger than 8000 chars.
        large_code = "x = 1\n" * 2000  # ~12000 chars
        response = json.dumps({"symbols": [], "imports": [], "env_vars": [], "errors": []})
        fake = FakeLLMClient(response)
        ext = LLMExtractor.__new__(LLMExtractor)
        ext._client = fake

        path = _write_tmp(large_code)
        result = ext.extract_file(path, "large.rb", "ruby")
        # Should not crash.
        assert result is not None

    def test_llm_failure_returns_empty(self):
        fake = FakeLLMClient("")
        fake.ask = AsyncMock(side_effect=RuntimeError("API error"))
        ext = LLMExtractor.__new__(LLMExtractor)
        ext._client = fake

        path = _write_tmp("some code")
        result = ext.extract_file(path, "app.rb", "ruby")
        assert result.symbols == []
        assert result.imports == []
