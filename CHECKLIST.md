# Docbot Sprint Checklist

> **How to use:** Check items off as you complete them. If swapping roles mid-sprint, the incoming dev reads the checked/unchecked state to know exactly where things stand. Every task has its owned files listed so there's no ambiguity about what to touch.

---

## Phase 0: Interface Contracts

**Owner:** Dev A (reviewed by all)
**Branch:** `phase0/contracts`
**Files:** `src/docbot/models.py`

- [ ] Add `SourceFile` model (`path: str`, `language: str`)
- [ ] Add `FileExtraction` model (`symbols`, `imports`, `env_vars`, `raised_errors`, `citations`)
- [ ] Update `ScanResult`: rename `py_files` → `source_files` (type `list[SourceFile]`), add `languages: list[str]`
- [ ] Update `ScopeResult`: add `languages: list[str]` field
- [ ] Update `DocsIndex`: add `languages: list[str]` field
- [ ] Update `PublicSymbol.kind` docstring to include non-Python kinds
- [ ] Write the `Extractor` protocol signature in a doc comment (so Dev B knows the exact interface)
- [ ] All 4 devs reviewed and approved the contracts
- [ ] Merged `phase0/contracts` → `master`

---

## Phase 1: Parallel Development

### Dev A — Core Infrastructure

**Branch:** `phase1/core-infra`
**Owned files:** `scanner.py`, `llm.py`, `__init__.py`, `pyproject.toml`, `server.py`

#### Scanner Generalization (`src/docbot/scanner.py`)

- [ ] Add `LANGUAGE_EXTENSIONS` mapping (extension → language name)
  - [ ] Python (`.py`)
  - [ ] TypeScript (`.ts`, `.tsx`)
  - [ ] JavaScript (`.js`, `.jsx`)
  - [ ] Go (`.go`)
  - [ ] Rust (`.rs`)
  - [ ] Java (`.java`)
  - [ ] Kotlin (`.kt`)
  - [ ] C (`.c`, `.h`)
  - [ ] C++ (`.cpp`, `.hpp`, `.cc`)
  - [ ] Ruby (`.rb`)
  - [ ] PHP (`.php`)
  - [ ] Swift (`.swift`)
  - [ ] C# (`.cs`)
- [ ] Change scan loop: match any known source extension, not just `.py`
- [ ] Return `source_files: list[SourceFile]` instead of `py_files: list[str]`
- [ ] Populate `languages` field with all detected languages
- [ ] Generalize entrypoint detection
  - [ ] Python: `main.py`, `app.py`, `cli.py`, `wsgi.py`, `asgi.py`, `__main__.py`
  - [ ] JS/TS: `index.ts`, `index.js`, `app.ts`, `server.ts`, `main.ts`
  - [ ] Go: files containing `func main()`
  - [ ] Rust: `main.rs`, `lib.rs`
  - [ ] Java: files containing `public static void main`
  - [ ] General: `Dockerfile`, `docker-compose.yml`, `Makefile`
- [ ] Generalize package detection
  - [ ] Python: `__init__.py`
  - [ ] JS/TS: `package.json`, `index.ts`, `index.js`
  - [ ] Go: directories with `.go` files
  - [ ] Rust: `Cargo.toml`
  - [ ] Java: directories with `.java` files
- [ ] Expand `SKIP_DIRS`: add `vendor`, `target`, `.cargo`, `bin`, `obj`, `.next`, `.nuxt`, `.svelte-kit`, `coverage`, `.gradle`

#### LLM Client (`src/docbot/llm.py`)

- [ ] Review `max_tokens` default — increase if needed for extraction prompts
- [ ] Ensure `chat()` interface is sufficient for Dev B's LLM extractor needs
- [ ] No breaking changes to existing interface

#### Dependencies (`pyproject.toml`)

- [ ] Add `tree-sitter>=0.21`
- [ ] Add grammar packages: `tree-sitter-javascript`, `tree-sitter-typescript`, `tree-sitter-go`, `tree-sitter-rust`, `tree-sitter-java`
- [ ] Add webapp deps: `fastapi`, `uvicorn[standard]`, `sse-starlette`

#### Exports (`src/docbot/__init__.py`)

- [ ] Update exports if any public names changed

#### Webapp Server Skeleton (`src/docbot/server.py` — new file)

- [ ] Create FastAPI app
- [ ] `GET /api/index` — return DocsIndex JSON
- [ ] `GET /api/scopes` — list scopes with metadata
- [ ] `GET /api/graph` — dependency graph
- [ ] Basic CORS configuration

#### Self-check before merge

- [ ] `scan_repo()` returns valid `ScanResult` with `source_files` and `languages` on a Python project
- [ ] `scan_repo()` returns valid results on a TypeScript project
- [ ] `scan_repo()` returns valid results on a mixed-language project
- [ ] No import errors across the package

---

### Dev B — Extraction Engine

**Branch:** `phase1/extraction-engine`
**Owned files:** `extractors/*` (all new), `explorer.py`, `search.py`

#### Extractors Package Setup

- [ ] Create `src/docbot/extractors/__init__.py`
  - [ ] Export `get_extractor(language: str, llm_client=None) -> Extractor`
  - [ ] Router logic: Python → `PythonExtractor`, TS/JS/Go/Rust/Java → `TreeSitterExtractor`, else → `LLMExtractor`
- [ ] Create `src/docbot/extractors/base.py`
  - [ ] Define `Extractor` protocol with `extract_file(abs_path, rel_path, language) -> FileExtraction`
  - [ ] Re-export `FileExtraction` from models for convenience

#### Python Extractor (`src/docbot/extractors/python_extractor.py`)

- [ ] Move `_extract_file()` from `explorer.py`
- [ ] Move `_signature()` helper
- [ ] Move `_first_line_docstring()` helper
- [ ] Move `_safe_unparse()` helper
- [ ] Move `_ENV_RE` regex
- [ ] Wrap in `PythonExtractor` class implementing `Extractor` protocol
- [ ] Verify: produces identical output to the old `explorer.py` code on the same files

#### Tree-sitter Extractor (`src/docbot/extractors/treesitter_extractor.py`)

- [ ] `TreeSitterExtractor` class implementing `Extractor` protocol
- [ ] Language initialization: load correct grammar per language
- [ ] TypeScript/JavaScript queries
  - [ ] Functions (function declarations, arrow functions, method definitions)
  - [ ] Classes and interfaces
  - [ ] Imports (`import ... from`, `require()`)
  - [ ] Env vars (`process.env.X`)
  - [ ] Error throwing (`throw`)
- [ ] Go queries
  - [ ] Functions and methods
  - [ ] Structs and interfaces
  - [ ] Imports (`import "..."`, `import (...)`)
  - [ ] Env vars (`os.Getenv()`)
  - [ ] Error patterns (`return err`, `panic()`)
- [ ] Rust queries
  - [ ] Functions (`fn`), methods (`impl` blocks)
  - [ ] Structs, enums, traits
  - [ ] Imports (`use`)
  - [ ] Env vars (`std::env::var()`)
  - [ ] Error patterns (`panic!()`, `unwrap()`, `expect()`)
- [ ] Java queries
  - [ ] Methods, constructors
  - [ ] Classes, interfaces, enums
  - [ ] Imports (`import`)
  - [ ] Env vars (`System.getenv()`)
  - [ ] Error throwing (`throw`)
- [ ] All extractors return proper `Citation` objects with correct line numbers
- [ ] All extractors return proper `PublicSymbol` objects with correct `kind` values

#### LLM Fallback Extractor (`src/docbot/extractors/llm_extractor.py`)

- [ ] `LLMExtractor` class implementing `Extractor` protocol
- [ ] Accepts `LLMClient` instance in constructor
- [ ] Structured extraction prompt: asks for JSON matching `FileExtraction` shape
- [ ] JSON response parsing into `FileExtraction` model
- [ ] Truncation handling for files > 8K tokens
- [ ] Graceful error handling: returns empty `FileExtraction` on LLM failure, doesn't crash

#### Explorer Refactor (`src/docbot/explorer.py`)

- [ ] Remove `import ast` and all AST-specific code
- [ ] Remove `_extract_file()`, `_signature()`, `_first_line_docstring()`, `_safe_unparse()`
- [ ] Remove `_ENV_RE` regex
- [ ] Import `get_extractor` from `extractors`
- [ ] `explore_scope()`: iterate files, detect language, call `get_extractor(lang).extract_file()`
- [ ] `explore_scope()`: populate `ScopeResult.languages` from the files in the scope
- [ ] `enrich_scope_with_llm()`: update `_EXPLORER_SYSTEM` — replace "Python" with dynamic language
- [ ] `enrich_scope_with_llm()`: update `_EXPLORER_PROMPT` — replace "Python" with dynamic language
- [ ] Keep `_build_source_snippets()` unchanged

#### Semantic Search (`src/docbot/search.py`)

- [ ] `SearchIndex` class
- [ ] Index extracted symbols
- [ ] `search(query) -> list[Citation]` implementation

#### Self-check before merge

- [ ] `PythonExtractor` produces identical results to old `_extract_file()` on docbot's own source
- [ ] `TreeSitterExtractor` correctly extracts symbols from a TypeScript file
- [ ] `TreeSitterExtractor` correctly extracts symbols from a Go file
- [ ] `LLMExtractor` returns valid `FileExtraction` for a Ruby file (or similar unsupported language)
- [ ] `get_extractor()` routes correctly for all supported languages
- [ ] `explore_scope()` works with the new extraction layer
- [ ] No import errors across the package

---

### Dev C — Pipeline & Presentation

**Branch:** `phase1/pipeline-prompts`
**Owned files:** `planner.py`, `reducer.py`, `renderer.py`, `tracker.py`, `viz_server.py`, `_viz_html.py`

#### Planner Updates (`src/docbot/planner.py`)

- [ ] Expand `_CROSSCUTTING_RE`: add `utils`, `helpers`, `common`, `shared`, `types`, `models`
- [ ] `_PLANNER_SYSTEM`: replace "Python repository" with `{languages}` placeholder
- [ ] `_PLANNER_PROMPT`: replace "Python repository" with `{languages}` placeholder
- [ ] `_PLANNER_PROMPT`: replace "Python files" references with "source files"
- [ ] `build_plan()`: accept and work with `source_files: list[SourceFile]` instead of `py_files`
- [ ] `build_plan()`: update file count and listing to use `source_files`
- [ ] `refine_plan_with_llm()`: include detected languages in prompt context
- [ ] `refine_plan_with_llm()`: update file listing format to include language info

#### Reducer Updates (`src/docbot/reducer.py`)

- [ ] `_compute_scope_edges()`: generalize beyond Python dotted import paths
  - [ ] File-path-based matching as primary strategy
  - [ ] Prefix matching fallback for dotted imports
  - [ ] Handle JS/TS-style relative imports (`./`, `../`)
  - [ ] Handle Go package imports
- [ ] `_ANALYSIS_SYSTEM`: replace "Python codebase" with dynamic language info
- [ ] `_ANALYSIS_PROMPT`: replace "Python repository" with dynamic language info
- [ ] `_MERMAID_SYSTEM`: replace "Python" references with dynamic language info
- [ ] `_MERMAID_PROMPT`: replace "Python" references with dynamic language info
- [ ] `reduce_with_llm()`: accept and pass through `languages` parameter
- [ ] `_build_scope_block()`: include language info per scope

#### Renderer Updates (`src/docbot/renderer.py`)

- [ ] `_SCOPE_DOC_SYSTEM`: replace "Python" with dynamic language
- [ ] `_SCOPE_DOC_PROMPT`: replace "Python repository" with dynamic language
- [ ] `_README_SYSTEM`: replace "Python" with dynamic language
- [ ] `_README_PROMPT`: replace "Python repository" with dynamic language
- [ ] `_ARCH_SYSTEM`: replace "Python" with dynamic language
- [ ] `_ARCH_PROMPT`: replace "Python repository" with dynamic language
- [ ] Template fallbacks: replace "Python files" with "source files" throughout
- [ ] `_render_index_html()`: show detected languages in the HTML report header
- [ ] `_render_readme_template()`: reference languages instead of "Python"
- [ ] `_render_architecture_template()`: reference languages instead of "Python"
- [ ] All `_generate_*_llm()` functions: accept and use `languages` parameter

#### Webapp Server Skeleton (Moved to Dev A)

- (Dev A now owns `server.py`)

#### Self-check before merge

- [ ] All prompt strings contain `{languages}` or dynamic language references, zero hardcoded "Python"
- [ ] `build_plan()` works with `source_files` input (can unit test with mock data)
- [ ] `_compute_scope_edges()` handles non-Python import formats
- [ ] `server.py` starts and serves `/api/index` endpoint
- [ ] No import errors across the package

---

### Dev D — Frontend Experience

**Branch:** `phase1/webapp-frontend`
**Owned files:** `webapp/*`

#### Frontend Scaffold (`webapp/`)

- [ ] Scaffold: Vite + React + TypeScript + Tailwind
- [ ] Build config: output to `webapp/dist/`
- [ ] Mock Data Layer: create `src/mocks.ts` with explicit types matching `models.py` contracts
  - [ ] Mock `DocsIndex`
  - [ ] Mock `ScopeResult` list
  - [ ] Mock `ScopeResult` detail (symbols, citations)
  - [ ] Mock Dependency Graph (nodes/edges)

#### UI Components

- [ ] **Interactive System Graph**
  - [ ] ReactFlow setup (read from mocks)
  - [ ] Nodes colored by type, Edges for dependencies
  - [ ] Zoom/Pan/Click-to-detail
- [ ] **Chat Panel**
  - [ ] Message feed with mock messages
  - [ ] Markdown rendering
  - [ ] Mermaid support
- [ ] **Code Viewer**
  - [ ] Implementation with Shiki/Prism
  - [ ] Line highlighting
- [ ] **Documentation Browser**
  - [ ] Render markdown docs (mocks)

#### Self-check before merge

- [ ] `npm run dev` launches the UI
- [ ] UI is fully navigable using mock data
- [ ] `npm run build` creates valid static assets in `dist/`

---

## Phase 2: Integration & Webapp

> Phase 2 begins after all four Phase 1 branches merge to master.

### Dev A — Integration Wiring

**Branch:** `phase2/integration`
**Owned files:** `orchestrator.py`, `cli.py`, `server.py`

#### Orchestrator (`src/docbot/orchestrator.py`)

- [ ] Replace `scan.py_files` references with `scan.source_files`
- [ ] Replace `len(scan.py_files)` with `len(scan.source_files)`
- [ ] Console output: show detected languages (e.g. "Found 45 source files: 30 Python, 10 TypeScript, 5 Go")
- [ ] Console output: show file counts per language
- [ ] Pass `languages` through to `reduce_with_llm()` and `render_with_llm()`
- [ ] Update "No Python files found" → "No source files found"
- [ ] Verify: `_explore_one()` works with new `explore_scope()` signature
- [ ] Verify: LLM extractor receives `llm_client` correctly for fallback languages

#### Server Completion (`src/docbot/server.py`)

- [ ] `GET /api/source/{file_path}` — serve source code
- [ ] `GET /api/search?q=term` — search symbols
- [ ] `POST /api/chat` — AI chat endpoint
- [ ] `GET /api/tours` — list guided tours
- [ ] Tour generation logic integration

#### CLI (`src/docbot/cli.py`)

- [ ] Update `app` help text: "Generate thorough documentation for a repository" (drop "Python")
- [ ] Update `run` command help: "Scan, explore, and generate documentation for REPO"
- [ ] `--no-llm` behavior: tree-sitter/AST extraction still runs, LLM enrichment skipped, unsupported languages get basic file listing
- [ ] Add `serve` subcommand
  - [ ] Accepts run directory or repo path
  - [ ] `--port` option (default 8080)
  - [ ] If repo path given: run analysis first, then serve
  - [ ] If run directory given: serve immediately
  - [ ] Auto-open browser

#### Self-check before merge

- [ ] `docbot /path/to/python/project` — full pipeline works, same quality as before
- [ ] `docbot /path/to/typescript/project` — produces meaningful docs
- [ ] `docbot /path/to/go/project` — produces meaningful docs
- [ ] `docbot /path/to/mixed/monorepo` — handles all languages
- [ ] `docbot serve /path/to/run/dir` — starts server, opens browser
- [ ] `docbot --no-llm /path/to/project` — works for supported languages (Python, TS, Go, Rust, Java)
- [ ] Console output shows language breakdown

---

### Dev B — Extended Coverage (or reassign to help Dev C)

**Branch:** `phase2/extended-extractors`
**Owned files:** `extractors/*`, `tests/*`

- [ ] Add tree-sitter grammar: Kotlin
- [ ] Add tree-sitter grammar: C#
- [ ] Add tree-sitter grammar: Swift
- [ ] Add tree-sitter grammar: Ruby
- [ ] Write tests: `tests/test_python_extractor.py`
- [ ] Write tests: `tests/test_treesitter_extractor.py`
- [ ] Write tests: `tests/test_llm_extractor.py`
- [ ] Write tests: `tests/test_scanner.py`
- [ ] Write tests: `tests/test_explorer.py`

---

### Dev C — Webapp (Backend + Frontend)

**Branch:** `phase2/webapp`
**Owned files:** `server.py`, `webapp/*`, `tracker.py`, `viz_server.py`, `_viz_html.py`

- [ ] Serve static files from `webapp/dist/` at `/`

#### Backend Completion (Moved to Dev A)

- (Dev A now owns `server.py`)

---

### Dev D — Webapp Integration

**Branch:** `phase2/webapp-bind`
**Owned files:** `webapp/*`

#### Integration

- [ ] Switch API client from mocks to real endpoints (Dev A's server)
- [ ] Test end-to-end flow:
  - [ ] Graph loads real analysis data
  - [ ] Source viewer loads real file content
  - [ ] Chat sends/receives real messages
- [ ] Polish loading states and error handling

#### Self-check before merge

- [ ] Frontend works with real backend (served via `docbot serve`)
- [ ] No regressions in UI features

#### Existing Viz Integration

- [ ] Decide: integrate existing D3 pipeline viz into webapp OR deprecate
- [ ] If integrating: adapt `tracker.py` to emit events to webapp
- [ ] If deprecating: mark `viz_server.py` and `_viz_html.py` as legacy

#### Self-check before merge

- [ ] `docbot serve` opens browser with working webapp
- [ ] Graph renders correctly with real data from a docbot run
- [ ] Chat answers questions about the codebase
- [ ] Chat generates Mermaid diagrams that render inline
- [ ] Clicking citations opens code viewer at correct line
- [ ] Guided tours step through correctly
- [ ] Works on both small (10 files) and medium (200+ files) codebases

---

## Role Swap Guide

If a developer needs to take over another's work mid-sprint:

1. **Read their checklist above** — checked items are done, unchecked items remain
2. **Check out their branch** — all their work-in-progress is there
3. **Only touch their owned files** — the file ownership table in `TEAM_PLAN.md` is the source of truth
4. **Update this checklist** as you complete items

### Quick reference: who owns what

| File              | Owner           |
| ----------------- | --------------- |
| `models.py`       | Dev A           |
| `scanner.py`      | Dev A           |
| `llm.py`          | Dev A           |
| `__init__.py`     | Dev A           |
| `orchestrator.py` | Dev A           |
| `cli.py`          | Dev A           |
| `pyproject.toml`  | Dev A           |
| `extractors/*`    | Dev B           |
| `explorer.py`     | Dev B           |
| `planner.py`      | Dev C           |
| `reducer.py`      | Dev C           |
| `renderer.py`     | Dev C           |
| `tracker.py`      | Dev C           |
| `viz_server.py`   | Dev C           |
| `_viz_html.py`    | Dev C           |
| `server.py`       | Dev A           |
| `search.py`       | Dev B           |
| `webapp/*`        | Dev D           |
| `tests/*`         | Dev B (Phase 2) |
