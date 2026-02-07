"""Tests for the tree-sitter extractor across all supported languages."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from docbot.extractors.treesitter_extractor import TreeSitterExtractor, _grammar_cache


@pytest.fixture(autouse=True)
def _clear_grammar_cache():
    """Ensure a clean grammar cache for each test."""
    _grammar_cache.clear()
    yield
    _grammar_cache.clear()


@pytest.fixture
def extractor() -> TreeSitterExtractor:
    return TreeSitterExtractor()


def _write_tmp(code: str, suffix: str) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8")
    f.write(code)
    f.close()
    return Path(f.name)


# ---- JavaScript ----

class TestJavaScript:
    def test_function_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("function greet(name) { return 'hi ' + name; }", ".js")
        result = extractor.extract_file(path, "app.js", "javascript")
        names = [s.name for s in result.symbols]
        assert "greet" in names

    def test_class_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("class UserService { constructor() {} }", ".js")
        result = extractor.extract_file(path, "app.js", "javascript")
        names = [s.name for s in result.symbols]
        assert "UserService" in names

    def test_import_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("import { Router } from 'express';\nconst db = require('pg');", ".js")
        result = extractor.extract_file(path, "app.js", "javascript")
        assert "express" in result.imports or "'express'" in result.imports

    def test_env_var_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("const key = process.env.API_KEY;", ".js")
        result = extractor.extract_file(path, "app.js", "javascript")
        env_names = [e.name for e in result.env_vars]
        assert "API_KEY" in env_names

    def test_throw_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("function fail() { throw new Error('bad'); }", ".js")
        result = extractor.extract_file(path, "app.js", "javascript")
        assert len(result.raised_errors) >= 1


# ---- TypeScript ----

class TestTypeScript:
    def test_function_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("export function createApp(config: Config): void {}", ".ts")
        result = extractor.extract_file(path, "app.ts", "typescript")
        names = [s.name for s in result.symbols]
        assert "createApp" in names

    def test_interface_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("export interface AppConfig { port: number; host: string; }", ".ts")
        result = extractor.extract_file(path, "types.ts", "typescript")
        names = [s.name for s in result.symbols]
        assert "AppConfig" in names
        kinds = {s.name: s.kind for s in result.symbols}
        assert kinds["AppConfig"] == "interface"

    def test_type_alias_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("export type UserId = string;", ".ts")
        result = extractor.extract_file(path, "types.ts", "typescript")
        names = [s.name for s in result.symbols]
        assert "UserId" in names

    def test_class_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("export class AppController { constructor() {} }", ".ts")
        result = extractor.extract_file(path, "app.ts", "typescript")
        names = [s.name for s in result.symbols]
        assert "AppController" in names


# ---- Go ----

class TestGo:
    def test_function_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("package main\n\nfunc Hello(name string) string {\n\treturn name\n}", ".go")
        result = extractor.extract_file(path, "main.go", "go")
        names = [s.name for s in result.symbols]
        assert "Hello" in names

    def test_struct_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("package main\n\ntype User struct {\n\tName string\n\tAge int\n}", ".go")
        result = extractor.extract_file(path, "models.go", "go")
        names = [s.name for s in result.symbols]
        assert "User" in names
        kinds = {s.name: s.kind for s in result.symbols}
        assert kinds["User"] == "struct"

    def test_interface_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("package main\n\ntype Logger interface {\n\tLog(msg string)\n}", ".go")
        result = extractor.extract_file(path, "interfaces.go", "go")
        names = [s.name for s in result.symbols]
        assert "Logger" in names

    def test_import_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp('package main\n\nimport (\n\t"fmt"\n\t"os"\n)', ".go")
        result = extractor.extract_file(path, "main.go", "go")
        assert "fmt" in result.imports
        assert "os" in result.imports

    def test_env_var_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp('package main\n\nimport "os"\n\nfunc Init() {\n\tkey := os.Getenv("API_KEY")\n\t_ = key\n}', ".go")
        result = extractor.extract_file(path, "main.go", "go")
        env_names = [e.name for e in result.env_vars]
        assert "API_KEY" in env_names


# ---- Rust ----

class TestRust:
    def test_function_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("pub fn process(data: &str) -> String {\n    data.to_string()\n}", ".rs")
        result = extractor.extract_file(path, "lib.rs", "rust")
        names = [s.name for s in result.symbols]
        assert "process" in names

    def test_struct_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("pub struct Config {\n    pub name: String,\n}", ".rs")
        result = extractor.extract_file(path, "lib.rs", "rust")
        names = [s.name for s in result.symbols]
        assert "Config" in names

    def test_enum_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("pub enum Status {\n    Active,\n    Inactive,\n}", ".rs")
        result = extractor.extract_file(path, "lib.rs", "rust")
        names = [s.name for s in result.symbols]
        assert "Status" in names
        kinds = {s.name: s.kind for s in result.symbols}
        assert kinds["Status"] == "enum"

    def test_trait_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("pub trait Handler {\n    fn handle(&self);\n}", ".rs")
        result = extractor.extract_file(path, "lib.rs", "rust")
        names = [s.name for s in result.symbols]
        assert "Handler" in names

    def test_use_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("use std::collections::HashMap;\nuse std::env;", ".rs")
        result = extractor.extract_file(path, "lib.rs", "rust")
        assert len(result.imports) >= 2

    def test_panic_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp('fn fail() {\n    panic!("something broke");\n}', ".rs")
        result = extractor.extract_file(path, "lib.rs", "rust")
        assert len(result.raised_errors) >= 1


# ---- Java ----

class TestJava:
    def test_class_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("public class App {\n    public void run() {}\n}", ".java")
        result = extractor.extract_file(path, "App.java", "java")
        names = [s.name for s in result.symbols]
        assert "App" in names

    def test_method_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("public class App {\n    public String greet(String name) {\n        return name;\n    }\n}", ".java")
        result = extractor.extract_file(path, "App.java", "java")
        names = [s.name for s in result.symbols]
        assert "greet" in names

    def test_interface_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("public interface Handler {\n    void handle();\n}", ".java")
        result = extractor.extract_file(path, "Handler.java", "java")
        names = [s.name for s in result.symbols]
        assert "Handler" in names

    def test_import_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("import java.util.List;\nimport java.util.Map;\n\npublic class App {}", ".java")
        result = extractor.extract_file(path, "App.java", "java")
        assert len(result.imports) >= 2

    def test_throw_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp('public class App {\n    void fail() {\n        throw new RuntimeException("bad");\n    }\n}', ".java")
        result = extractor.extract_file(path, "App.java", "java")
        assert len(result.raised_errors) >= 1


# ---- Kotlin ----

class TestKotlin:
    def test_function_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("fun greet(name: String): String {\n    return \"Hello $name\"\n}", ".kt")
        result = extractor.extract_file(path, "App.kt", "kotlin")
        names = [s.name for s in result.symbols]
        assert "greet" in names

    def test_class_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("data class User(val name: String, val age: Int)", ".kt")
        result = extractor.extract_file(path, "Models.kt", "kotlin")
        names = [s.name for s in result.symbols]
        assert "User" in names


# ---- C# ----

class TestCSharp:
    def test_class_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("namespace App {\n    public class Program {\n        static void Main() {}\n    }\n}", ".cs")
        result = extractor.extract_file(path, "Program.cs", "csharp")
        names = [s.name for s in result.symbols]
        assert "Program" in names

    def test_method_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("public class App {\n    public string Greet(string name) {\n        return name;\n    }\n}", ".cs")
        result = extractor.extract_file(path, "App.cs", "csharp")
        names = [s.name for s in result.symbols]
        assert "Greet" in names


# ---- Ruby ----

class TestRuby:
    def test_method_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("def greet(name)\n  \"Hello #{name}\"\nend", ".rb")
        result = extractor.extract_file(path, "app.rb", "ruby")
        names = [s.name for s in result.symbols]
        assert "greet" in names

    def test_class_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("class UserService\n  def initialize(db)\n    @db = db\n  end\nend", ".rb")
        result = extractor.extract_file(path, "user.rb", "ruby")
        names = [s.name for s in result.symbols]
        assert "UserService" in names


# ---- Swift ----

class TestSwift:
    def test_function_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("func greet(name: String) -> String {\n    return \"Hello \\(name)\"\n}", ".swift")
        result = extractor.extract_file(path, "app.swift", "swift")
        names = [s.name for s in result.symbols]
        assert "greet" in names

    def test_struct_extraction(self, extractor: TreeSitterExtractor):
        path = _write_tmp("struct User {\n    var name: String\n    var age: Int\n}", ".swift")
        result = extractor.extract_file(path, "models.swift", "swift")
        names = [s.name for s in result.symbols]
        assert "User" in names


# ---- General ----

class TestGeneral:
    def test_unsupported_language_returns_empty(self, extractor: TreeSitterExtractor):
        path = _write_tmp("print('hello')", ".py")
        result = extractor.extract_file(path, "mod.py", "python")
        assert result.symbols == []

    def test_empty_file(self, extractor: TreeSitterExtractor):
        path = _write_tmp("", ".js")
        result = extractor.extract_file(path, "empty.js", "javascript")
        assert result.symbols == []

    def test_supported_languages(self):
        ext = TreeSitterExtractor()
        assert "javascript" in ext.SUPPORTED
        assert "typescript" in ext.SUPPORTED
        assert "go" in ext.SUPPORTED
        assert "rust" in ext.SUPPORTED
        assert "java" in ext.SUPPORTED
        assert "kotlin" in ext.SUPPORTED
        assert "csharp" in ext.SUPPORTED
        assert "ruby" in ext.SUPPORTED
        assert "swift" in ext.SUPPORTED

    def test_citations_have_correct_file(self, extractor: TreeSitterExtractor):
        path = _write_tmp("function hello() { return 1; }", ".js")
        result = extractor.extract_file(path, "src/util.js", "javascript")
        for cit in result.citations:
            assert cit.file == "src/util.js"
