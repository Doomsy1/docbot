# Docbot Sprint Checklist

> **How to use:** Check items off as you complete them. If swapping roles mid-sprint, the incoming dev reads the checked/unchecked state to know exactly where things stand. Every task has its owned files listed so there's no ambiguity about what to touch.

---

## Phase 0: Interface Contracts

**Owner:** Dev A (reviewed by all)
**Branch:** `phase0/contracts`
**Files:** `src/docbot/models.py`

- [x] Add `SourceFile` model (`path: str`, `language: str`)
- [x] Add `FileExtraction` model (`symbols`, `imports`, `env_vars`, `raised_errors`, `citations`)
- [x] Update `ScanResult`: rename `py_files` → `source_files` (type `list[SourceFile]`), add `languages: list[str]`
- [x] Update `ScopeResult`: add `languages: list[str]` field
- [x] Update `DocsIndex`: add `languages: list[str]` field
- [x] Update `PublicSymbol.kind` docstring to include non-Python kinds
- [x] Write the `Extractor` protocol signature in a doc comment (so Dev B knows the exact interface)
- [ ] All 4 devs reviewed and approved the contracts
- [ ] Merged `phase0/contracts` → `master`

---

## Phase 1: Parallel Development

### Dev A — Core Infrastructure

**Branch:** `phase1/core-infra`
**Owned files:** `scanner.py`, `llm.py`, `__init__.py`, `pyproject.toml`, `server.py`

#### Scanner Generalization (`src/docbot/scanner.py`)

- [x] Add `LANGUAGE_EXTENSIONS` mapping (extension → language name)
  - [x] Python (`.py`)
  - [x] TypeScript (`.ts`, `.tsx`)
  - [x] JavaScript (`.js`, `.jsx`)
  - [x] Go (`.go`)
  - [x] Rust (`.rs`)
  - [x] Java (`.java`)
  - [x] Kotlin (`.kt`)
  - [x] C (`.c`, `.h`)
  - [x] C++ (`.cpp`, `.hpp`, `.cc`)
  - [x] Ruby (`.rb`)
  - [x] PHP (`.php`)
  - [x] Swift (`.swift`)
  - [x] C# (`.cs`)
- [x] Change scan loop: match any known source extension, not just `.py`
- [x] Return `source_files: list[SourceFile]` instead of `py_files: list[str]`
- [x] Populate `languages` field with all detected languages
- [x] Generalize entrypoint detection
  - [x] Python: `main.py`, `app.py`, `cli.py`, `wsgi.py`, `asgi.py`, `__main__.py`
  - [x] JS/TS: `index.ts`, `index.js`, `app.ts`, `server.ts`, `main.ts`
  - [x] Go: files containing `func main()`
  - [x] Rust: `main.rs`, `lib.rs`
  - [x] Java: files containing `public static void main`
  - [x] General: `Dockerfile`, `docker-compose.yml`, `Makefile`
- [x] Generalize package detection
  - [x] Python: `__init__.py`
  - [x] JS/TS: `package.json`, `index.ts`, `index.js`
  - [x] Go: directories with `.go` files
  - [x] Rust: `Cargo.toml`
  - [x] Java: directories with `.java` files
- [x] Expand `SKIP_DIRS`: add `vendor`, `target`, `.cargo`, `bin`, `obj`, `.next`, `.nuxt`, `.svelte-kit`, `coverage`, `.gradle`

#### LLM Client (`src/docbot/llm.py`)

- [x] Review `max_tokens` default — increase if needed for extraction prompts
- [x] Ensure `chat()` interface is sufficient for Dev B's LLM extractor needs
- [x] No breaking changes to existing interface

#### Dependencies (`pyproject.toml`)

- [x] Add `tree-sitter>=0.21`
- [x] Add grammar packages: `tree-sitter-javascript`, `tree-sitter-typescript`, `tree-sitter-go`, `tree-sitter-rust`, `tree-sitter-java`
- [x] Add webapp deps: `fastapi`, `uvicorn[standard]`, `sse-starlette`

#### Exports (`src/docbot/__init__.py`)

- [x] Update exports if any public names changed

#### Webapp Server Skeleton (`src/docbot/server.py` — new file)

- [x] Create FastAPI app
- [x] `GET /api/index` — return DocsIndex JSON
- [x] `GET /api/scopes` — list scopes with metadata
- [x] `GET /api/graph` — dependency graph
- [x] `GET /api/search` — search symbols
- [x] `GET /api/files/{path}` — serve source code
- [x] `GET /api/fs` — file structure tree
- [x] Basic CORS configuration

#### Self-check before merge

- [x] `scan_repo()` returns valid `ScanResult` with `source_files` and `languages` on a Python project
- [x] `scan_repo()` returns valid results on a TypeScript project
- [x] `scan_repo()` returns valid results on a mixed-language project
- [x] No import errors across the package

---

### Dev B — Extraction Engine

**Branch:** `phase1/extraction-engine`
**Owned files:** `extractors/*` (all new), `explorer.py`, `search.py`

#### Extractors Package Setup

- [x] Create `src/docbot/extractors/__init__.py`
  - [x] Export `get_extractor(language: str, llm_client=None) -> Extractor`
  - [x] Router logic: Python → `PythonExtractor`, TS/JS/Go/Rust/Java → `TreeSitterExtractor`, else → `LLMExtractor`
- [x] Create `src/docbot/extractors/base.py`
  - [x] Define `Extractor` protocol with `extract_file(abs_path, rel_path, language) -> FileExtraction`
  - [x] Re-export `FileExtraction` from models for convenience

#### Python Extractor (`src/docbot/extractors/python_extractor.py`)

- [x] Move `_extract_file()` from `explorer.py`
- [x] Move `_signature()` helper
- [x] Move `_first_line_docstring()` helper
- [x] Move `_safe_unparse()` helper
- [x] Move `_ENV_RE` regex
- [x] Wrap in `PythonExtractor` class implementing `Extractor` protocol
- [x] Verify: produces identical output to the old `explorer.py` code on the same files

#### Tree-sitter Extractor (`src/docbot/extractors/treesitter_extractor.py`)

- [x] `TreeSitterExtractor` class implementing `Extractor` protocol
- [x] Language initialization: load correct grammar per language (tree-sitter grammars loaded for all 9 languages)
- [x] TypeScript/JavaScript queries (regex-based fallback implemented)
  - [x] Functions (function declarations, arrow functions, method definitions)
  - [x] Classes and interfaces
  - [x] Imports (`import ... from`, `require()`)
  - [x] Env vars (`process.env.X`)
  - [x] Error throwing (`throw`)
- [x] Go queries (regex-based fallback implemented)
  - [x] Functions and methods
  - [x] Structs and interfaces
  - [x] Imports (`import "..."`, `import (...)`)
  - [x] Env vars (`os.Getenv()`)
  - [x] Error patterns (`return err`, `panic()`)
- [x] Rust queries (regex-based fallback implemented)
  - [x] Functions (`fn`), methods (`impl` blocks)
  - [x] Structs, enums, traits
  - [x] Imports (`use`)
  - [x] Env vars (`std::env::var()`)
  - [x] Error patterns (`panic!()`, `unwrap()`, `expect()`)
- [x] Java queries (regex-based fallback implemented)
  - [x] Methods, constructors
  - [x] Classes, interfaces, enums
  - [x] Imports (`import`)
  - [x] Env vars (`System.getenv()`)
  - [x] Error throwing (`throw`)
- [x] All extractors return proper `Citation` objects with correct line numbers
- [x] All extractors return proper `PublicSymbol` objects with correct `kind` values

#### LLM Fallback Extractor (`src/docbot/extractors/llm_extractor.py`)

- [x] `LLMExtractor` class implementing `Extractor` protocol
- [x] Accepts `LLMClient` instance in constructor
- [x] Structured extraction prompt: asks for JSON matching `FileExtraction` shape
- [x] JSON response parsing into `FileExtraction` model
- [x] Truncation handling for files > 8K tokens
- [x] Graceful error handling: returns empty `FileExtraction` on LLM failure, doesn't crash

#### Explorer Refactor (`src/docbot/explorer.py`)

- [x] Remove `import ast` and all AST-specific code
- [x] Remove `_extract_file()`, `_signature()`, `_first_line_docstring()`, `_safe_unparse()`
- [x] Remove `_ENV_RE` regex
- [x] Import `get_extractor` from `extractors`
- [x] `explore_scope()`: iterate files, detect language, call `get_extractor(lang).extract_file()`
- [x] `explore_scope()`: populate `ScopeResult.languages` from the files in the scope
- [x] `enrich_scope_with_llm()`: update `_EXPLORER_SYSTEM` — replace "Python" with dynamic language
- [x] `enrich_scope_with_llm()`: update `_EXPLORER_PROMPT` — replace "Python" with dynamic language
- [x] Keep `_build_source_snippets()` unchanged

#### Semantic Search (`src/docbot/search.py`)

- [x] `SearchIndex` class
- [x] Index extracted symbols
- [x] `search(query) -> list[Citation]` implementation

#### Self-check before merge

- [x] `PythonExtractor` produces identical results to old `_extract_file()` on docbot's own source
- [x] `TreeSitterExtractor` correctly extracts symbols from a TypeScript file (regex fallback)
- [x] `TreeSitterExtractor` correctly extracts symbols from a Go file (regex fallback)
- [x] `LLMExtractor` returns valid `FileExtraction` for a Ruby file (or similar unsupported language)
- [x] `get_extractor()` routes correctly for all supported languages
- [x] `explore_scope()` works with the new extraction layer
- [x] No import errors across the package

---

### Dev C — Pipeline & Presentation

**Branch:** `phase1/pipeline-prompts`
**Owned files:** `planner.py`, `reducer.py`, `renderer.py`, `tracker.py`, `viz_server.py`, `_viz_html.py`

#### Planner Updates (`src/docbot/planner.py`)

- [x] Expand `_CROSSCUTTING_RE`: add `utils`, `helpers`, `common`, `shared`, `types`, `models`
- [x] `_PLANNER_SYSTEM`: replace "Python repository" with `{languages}` placeholder
- [x] `_PLANNER_PROMPT`: replace "Python repository" with `{languages}` placeholder
- [x] `_PLANNER_PROMPT`: replace "Python files" references with "source files"
- [x] `build_plan()`: accept and work with `source_files: list[SourceFile]` instead of `py_files`
- [x] `build_plan()`: update file count and listing to use `source_files`
- [x] `refine_plan_with_llm()`: include detected languages in prompt context
- [x] `refine_plan_with_llm()`: update file listing format to include language info

#### Reducer Updates (`src/docbot/reducer.py`)

- [x] `_compute_scope_edges()`: generalize beyond Python dotted import paths
  - [x] File-path-based matching as primary strategy
  - [x] Prefix matching fallback for dotted imports
  - [x] Handle JS/TS-style relative imports (`./`, `../`)
  - [x] Handle Go package imports
- [x] `_ANALYSIS_SYSTEM`: replace "Python codebase" with dynamic language info
- [x] `_ANALYSIS_PROMPT`: replace "Python repository" with dynamic language info
- [x] `_MERMAID_SYSTEM`: replace "Python" references with dynamic language info
- [x] `_MERMAID_PROMPT`: replace "Python" references with dynamic language info
- [x] `reduce_with_llm()`: accept and pass through `languages` parameter
- [x] `_build_scope_block()`: include language info per scope

#### Renderer Updates (`src/docbot/renderer.py`)

- [x] `_SCOPE_DOC_SYSTEM`: replace "Python" with dynamic language
- [x] `_SCOPE_DOC_PROMPT`: replace "Python repository" with dynamic language
- [x] `_README_SYSTEM`: replace "Python" with dynamic language
- [x] `_README_PROMPT`: replace "Python repository" with dynamic language
- [x] `_ARCH_SYSTEM`: replace "Python" with dynamic language
- [x] `_ARCH_PROMPT`: replace "Python repository" with dynamic language
- [x] Template fallbacks: replace "Python files" with "source files" throughout
- [x] `_render_index_html()`: show detected languages in the HTML report header
- [x] `_render_readme_template()`: reference languages instead of "Python"
- [x] `_render_architecture_template()`: reference languages instead of "Python"
- [x] All `_generate_*_llm()` functions: accept and use `languages` parameter

#### Webapp Server Skeleton (Moved to Dev A)

- (Dev A now owns `server.py`)

#### Self-check before merge

- [x] All prompt strings contain `{languages}` or dynamic language references, zero hardcoded "Python"
- [x] `build_plan()` works with `source_files` input (can unit test with mock data)
- [x] `_compute_scope_edges()` handles non-Python import formats
- [x] `server.py` starts and serves `/api/index` endpoint
- [x] No import errors across the package

---

### Dev D — Frontend Experience

**Branch:** `phase1/webapp-frontend`
**Owned files:** `webapp/*`

#### Frontend Scaffold (`webapp/`)

- [x] Scaffold: Vite + React + TypeScript + Tailwind
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

- [x] Replace `scan.py_files` references with `scan.source_files`
- [x] Replace `len(scan.py_files)` with `len(scan.source_files)`
- [x] Console output: show detected languages (e.g. "Found 45 source files: 30 Python, 10 TypeScript, 5 Go")
- [x] Console output: show file counts per language
- [x] Pass `languages` through to `reduce_with_llm()` and `render_with_llm()`
- [x] Update "No Python files found" → "No source files found"
- [x] Verify: `_explore_one()` works with new `explore_scope()` signature
- [x] Verify: LLM extractor receives `llm_client` correctly for fallback languages

#### Server Completion (`src/docbot/server.py`)

- [x] `GET /api/source/{file_path}` — serve source code
- [x] `GET /api/search?q=term` — search symbols
- [x] `POST /api/chat` — AI chat endpoint (with Markdown + Mermaid)
- [x] `GET /api/tours` — list guided tours
- [x] Tour generation logic integration

#### CLI (`src/docbot/cli.py`)

- [x] Update `app` help text: "Generate thorough documentation for a repository" (drop "Python")
- [x] Update `run` command help: "Scan, explore, and generate documentation for REPO"
- [x] `--no-llm` behavior: tree-sitter/AST extraction still runs, LLM enrichment skipped, unsupported languages get basic file listing
- [x] Add `serve` subcommand
  - [x] Accepts run directory or repo path
  - [x] `--port` option (default 8000)
  - [x] If repo path given: run analysis first, then serve
  - [x] If run directory given: serve immediately
  - [x] Auto-open browser

#### Self-check before merge

- [x] `docbot /path/to/python/project` — full pipeline works, same quality as before
- [x] `docbot /path/to/typescript/project` — produces meaningful docs
- [x] `docbot /path/to/go/project` — produces meaningful docs
- [x] `docbot /path/to/mixed/monorepo` — handles all languages
- [x] `docbot serve /path/to/run/dir` — starts server and hosts webapp
- [x] `docbot --no-llm /path/to/project` — works for supported languages (Python, TS, Go, Rust, Java)
- [x] Console output shows language breakdown

---

### Dev B — Extended Coverage (or reassign to help Dev C)

**Branch:** `phase2/extended-extractors`
**Owned files:** `extractors/*`, `tests/*`

- [x] Add tree-sitter grammar: Kotlin
- [x] Add tree-sitter grammar: C#
- [x] Add tree-sitter grammar: Swift
- [x] Add tree-sitter grammar: Ruby
- [x] Write tests: `tests/test_python_extractor.py`
- [x] Write tests: `tests/test_treesitter_extractor.py`
- [x] Write tests: `tests/test_llm_extractor.py`
- [x] Write tests: `tests/test_scanner.py`
- [x] Write tests: `tests/test_explorer.py`

---

### Dev C — Webapp (Backend + Frontend)

**Branch:** `phase2/webapp`
**Owned files:** `server.py`, `webapp/*`, `tracker.py`, `viz_server.py`, `_viz_html.py`

- [x] Serve static files from `webapp/dist/` at `/`

#### Backend Completion (Moved to Dev A)

- (Dev A now owns `server.py`)

---

### Dev D — Webapp Integration

**Branch:** `phase2/webapp-bind`
**Owned files:** `webapp/*`

#### Integration

- [x] Switch API client from mocks to real endpoints (Dev A's server)
- [x] Test end-to-end flow:
  - [x] Graph loads real analysis data
  - [x] Source viewer loads real file content
  - [x] Chat sends/receives real messages
- [x] Polish loading states and error handling

#### Self-check before merge

- [x] Frontend works with real backend (served via `docbot serve`)
- [x] No regressions in UI features

#### Existing Viz Integration

- [x] Decide: integrate existing D3 pipeline viz into webapp OR deprecate
- [ ] If integrating: adapt `tracker.py` to emit events to webapp
- [x] If deprecating: mark `viz_server.py` and `_viz_html.py` as legacy

#### Self-check before merge

- [x] `docbot serve` hosts the working webapp
- [x] Graph renders correctly with real data from a docbot run
- [x] Chat answers questions about the codebase
- [x] Chat generates Mermaid diagrams that render inline
- [x] Clicking citations opens code viewer at correct line
- [x] Guided tours step through correctly
- [x] Works on both small (10 files) and medium (200+ files) codebases

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
