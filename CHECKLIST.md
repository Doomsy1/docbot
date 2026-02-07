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
- [x] All 4 devs reviewed and approved the contracts
- [x] Merged `phase0/contracts` → `master`

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

- [ ] Update exports if any public names changed

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
- [x] Language initialization: load correct grammar per language
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
- [x] Build config: output to `webapp/dist/`
- [x] Data Layer: real endpoints (replacing initial mocks)
  - [x] Real `DocsIndex`
  - [x] Real `ScopeResult` list
  - [x] Real `ScopeResult` detail
  - [x] Real Dependency Graph

#### UI Components

- [x] **Interactive System Graph**
  - [x] ReactFlow setup
  - [x] Nodes colored by type, Edges for dependencies
  - [x] Zoom/Pan/Click-to-detail
- [x] **Chat Panel**
  - [x] Message feed with natural language chat
  - [x] Markdown rendering
  - [x] Mermaid support
- [x] **Code Viewer**
  - [x] Implementation with Shiki
  - [x] Line highlighting (initial support)
- [x] **Documentation Browser**
  - [x] Render repository statistics and analysis

#### Self-check before merge

- [x] `npm run dev` launches the UI
- [x] UI is fully navigable with real data
- [x] `npm run build` creates valid static assets in `dist/`

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
  - [x] If run directory given: serve immediately
  - [x] Port number configuration (default 8000)

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

---

## Phase 3: Git-Integrated CLI

> **Goal:** Transform docbot from a standalone doc generator into a git-aware CLI tool with
> persistent `.docbot/` project directory and incremental updates based on git diffs.

> **Design decisions:** CWD default (optional path override), only config.toml git-tracked,
> init and generate are separate commands, git hooks opt-in via `docbot hook install`.

---

### Phase 3.0: Interface Contracts

**Owner:** Dev A (reviewed by all)
**Branch:** `phase3/contracts`
**Files:** `src/docbot/models.py`, `src/docbot/project.py` (stubs)

- [ ] Add `ProjectState` model to `models.py`:
  - [ ] `last_commit: str | None` -- git commit hash at last generate/update
  - [ ] `last_run_id: str | None` -- most recent run ID
  - [ ] `last_run_at: str | None` -- ISO timestamp of last run
  - [ ] `scope_file_map: dict[str, list[str]]` -- scope_id -> repo-relative file paths
- [ ] Add `DocbotConfig` model to `models.py`:
  - [ ] `model: str` (default: current DEFAULT_MODEL from llm.py)
  - [ ] `concurrency: int = 4`
  - [ ] `timeout: float = 120.0`
  - [ ] `max_scopes: int = 20`
  - [ ] `no_llm: bool = False`
- [ ] Create `src/docbot/project.py` with stub signatures:
  - [ ] `init_project(path: Path) -> Path`
  - [ ] `find_docbot_root(start: Path) -> Path | None`
  - [ ] `load_config(docbot_dir: Path) -> DocbotConfig`
  - [ ] `save_config(docbot_dir: Path, config: DocbotConfig) -> None`
  - [ ] `load_state(docbot_dir: Path) -> ProjectState`
  - [ ] `save_state(docbot_dir: Path, state: ProjectState) -> None`
- [ ] All devs reviewed and approved the contracts
- [ ] Merged `phase3/contracts` -> `master`

---

### Dev A -- CLI & Project Infrastructure

**Branch:** `phase3/cli-project`
**Owned files:** `cli.py`, `models.py`, `project.py` (new), `pyproject.toml`

#### Project Module (`src/docbot/project.py`)

- [ ] Implement `init_project(path)`:
  - [ ] Validate path is a git repo (check `.git/` exists)
  - [ ] Create `.docbot/` directory
  - [ ] Create subdirectories: `docs/`, `docs/modules/`, `scopes/`, `history/`
  - [ ] Write default `config.toml` with all DocbotConfig defaults
  - [ ] Write `.gitignore` that ignores everything except `config.toml` and `.gitignore`
  - [ ] Return the `.docbot/` path
- [ ] Implement `find_docbot_root(start)`:
  - [ ] Resolve `start` path
  - [ ] Walk `start` and its parents checking for `.docbot/` directory
  - [ ] Return the parent of `.docbot/` (the project root), or None if not found
- [ ] Implement `load_config(docbot_dir)`:
  - [ ] Read `config.toml` using `tomllib` (stdlib 3.11+)
  - [ ] Parse into `DocbotConfig` via `DocbotConfig(**data)`
  - [ ] Return default `DocbotConfig()` if file missing
- [ ] Implement `save_config(docbot_dir, config)`:
  - [ ] Format as TOML string (simple key = value, no nested tables needed)
  - [ ] Write to `config.toml`
- [ ] Implement `load_state(docbot_dir)`:
  - [ ] Read `state.json`, parse via `ProjectState.model_validate_json()`
  - [ ] Return empty `ProjectState()` if file missing or corrupt
- [ ] Implement `save_state(docbot_dir, state)`:
  - [ ] Write via `state.model_dump_json(indent=2)`

#### CLI Restructure (`src/docbot/cli.py`)

- [ ] Add `init` command:
  - [ ] Accept optional `path` argument (default: `Path.cwd()`)
  - [ ] Check if `.docbot/` already exists -- if so, print message and exit
  - [ ] Call `init_project(path)`
  - [ ] Print success message with next step: "Run `docbot generate` to create documentation"
- [ ] Add `generate` command:
  - [ ] Accept optional `path` argument (default: cwd)
  - [ ] Call `find_docbot_root()` to locate `.docbot/`; error if not found ("Run `docbot init` first")
  - [ ] Load config via `load_config()`
  - [ ] Merge CLI flag overrides (--model, -j, -t, etc.) into config
  - [ ] Load .env (reuse existing `_load_dotenv()`)
  - [ ] Build LLM client (reuse existing logic)
  - [ ] Set up visualization tracker (reuse existing logic)
  - [ ] Call `generate_async()` from orchestrator (Dev B implements)
  - [ ] Print completion summary
- [ ] Add `update` command:
  - [ ] Call `find_docbot_root()` to locate `.docbot/`; error if not found
  - [ ] Load config
  - [ ] Call `update_async()` from orchestrator (Dev B implements)
- [ ] Add `status` command:
  - [ ] Call `find_docbot_root()` to locate `.docbot/`
  - [ ] Load state via `load_state()`
  - [ ] If no state (never generated), print "No documentation generated yet"
  - [ ] Otherwise print: last commit hash, last run timestamp, scope count
  - [ ] Call `get_changed_files()` (Dev B) to show files changed since last doc
  - [ ] Map to affected scopes and print count
- [ ] Add `config` command:
  - [ ] No args: print all config key=value pairs
  - [ ] One arg (key): print that key's value
  - [ ] Two args (key, value): update config.toml with new value, print confirmation
- [ ] Add `hook` subcommand group:
  - [ ] `hook install`: call `install_hook()` (Dev B), print confirmation
  - [ ] `hook uninstall`: call `uninstall_hook()` (Dev B), print confirmation
- [ ] Adapt `serve` command:
  - [ ] If no path given, use `find_docbot_root()` to locate `.docbot/` and serve from there
  - [ ] If `.docbot/` not found, fall back to requiring explicit path (current behavior)
- [ ] Keep `run` as hidden alias (`@app.command(hidden=True)`) that delegates to `generate`

#### Dependencies (`pyproject.toml`)

- [ ] Version bump if appropriate
- [ ] Verify no new dependencies needed (tomllib is stdlib 3.11+)

#### Self-check before merge

- [ ] `docbot init` creates valid `.docbot/` with config.toml and .gitignore
- [ ] `docbot init` on non-git directory prints error
- [ ] `docbot init` on already-initialized project prints message
- [ ] `docbot config` prints all settings
- [ ] `docbot config model` prints model value
- [ ] `docbot config model some/model` updates config.toml
- [ ] `docbot generate` fails gracefully if not initialized
- [ ] `docbot serve` defaults to `.docbot/` if it exists
- [ ] `docbot run` works as alias for `generate`
- [ ] No import errors across the package

---

### Dev B -- Git Integration & Incremental Pipeline

**Branch:** `phase3/git-pipeline`
**Owned files:** `git_utils.py` (new), `orchestrator.py`, `hooks.py` (new), `scanner.py`

#### Git Utilities (`src/docbot/git_utils.py`)

- [ ] Create module with `from __future__ import annotations`
- [ ] Implement `get_current_commit(repo_root: Path) -> str | None`:
  - [ ] `subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True)`
  - [ ] Return stripped stdout, or None on any error
- [ ] Implement `get_changed_files(repo_root: Path, since_commit: str) -> list[str]`:
  - [ ] `subprocess.run(["git", "diff", "--name-only", f"{since_commit}..HEAD"], ...)`
  - [ ] Split stdout by newlines, filter empty strings
  - [ ] Normalize paths to forward slashes (Windows compat)
  - [ ] Return empty list on error
- [ ] Implement `is_commit_reachable(repo_root: Path, commit: str) -> bool`:
  - [ ] `subprocess.run(["git", "cat-file", "-t", commit], ...)`
  - [ ] Return True if returncode == 0
- [ ] Implement `get_repo_root(start: Path) -> Path | None`:
  - [ ] `subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, ...)`
  - [ ] Return `Path(stdout.strip())` or None on error

#### Scanner Update (`src/docbot/scanner.py`)

- [ ] Add `".docbot"` to `SKIP_DIRS` set

#### Orchestrator Refactor (`src/docbot/orchestrator.py`)

- [ ] Extract pipeline stage helpers from `run_async()`:
  - [ ] `_run_scan(repo_path, tracker)` -> ScanResult
  - [ ] `_run_plan(scan, max_scopes, llm_client, tracker)` -> list[ScopePlan]
  - [ ] `_run_explore(plans, repo_path, sem, timeout, llm_client, tracker)` -> list[ScopeResult]
  - [ ] `_run_reduce(scope_results, repo_path, llm_client, tracker)` -> DocsIndex
  - [ ] `_run_render(docs_index, output_dir, llm_client, tracker)` -> list[Path]
  - [ ] Each helper encapsulates its stage's tracker state management and console output
- [ ] Refactor `run_async()` to call the extracted helpers (verify no behavior change)
- [ ] Implement `generate_async(docbot_root: Path, config: DocbotConfig, llm_client, tracker)`:
  - [ ] `repo_path = docbot_root.parent`
  - [ ] Call all 5 pipeline stage helpers
  - [ ] Output to `docbot_root` instead of `runs/<run_id>/`
  - [ ] Save plan.json to `docbot_root / "plan.json"`
  - [ ] Save per-scope results to `docbot_root / "scopes" / "<scope_id>.json"`
  - [ ] Save docs_index.json to `docbot_root / "docs_index.json"`
  - [ ] Build scope_file_map from plan: `{plan.scope_id: plan.paths for plan in plans}`
  - [ ] Call `save_state()` with current commit, run_id, scope_file_map
  - [ ] Save RunMeta to `docbot_root / "history" / "<run_id>.json"`
- [ ] Implement `update_async(docbot_root: Path, config: DocbotConfig, llm_client, tracker)`:
  - [ ] Load state via `load_state()`
  - [ ] If no `last_commit`, print "No previous run found. Run `docbot generate` first." and return
  - [ ] Validate `last_commit` via `is_commit_reachable()`
    - [ ] If unreachable, print warning and fall back to `generate_async()`
  - [ ] Get changed files via `get_changed_files()`
  - [ ] If no changes, print "Documentation is up to date" and return
  - [ ] Map changed files to affected scope IDs using `state.scope_file_map`
  - [ ] Detect new files not in any scope:
    - [ ] Run scanner to find all current source files
    - [ ] Compare against all files in scope_file_map
    - [ ] If new files found, assign to closest scope by directory, or create new scope if needed
  - [ ] If >50% of scopes affected, print suggestion to run `docbot generate` instead
  - [ ] For affected scopes: re-run EXPLORE (load plan from plan.json, filter to affected)
  - [ ] For unaffected scopes: load ScopeResult from `.docbot/scopes/<scope_id>.json`
  - [ ] Merge all scope results (fresh + cached)
  - [ ] Re-run REDUCE (cross-scope analysis + Mermaid)
  - [ ] Call selective renderer functions (Dev C):
    - [ ] `render_scope_doc()` for each affected scope
    - [ ] `render_readme()` always (cross-cutting)
    - [ ] `render_architecture()` always (cross-cutting)
    - [ ] `render_api_reference()` always (fast, template-only)
    - [ ] `render_html_report()` always
  - [ ] Update state.json: new commit hash, updated scope_file_map
  - [ ] Save run history

#### Git Hooks (`src/docbot/hooks.py`)

- [ ] Create module with `from __future__ import annotations`
- [ ] Implement `install_hook(repo_root: Path) -> bool`:
  - [ ] Locate `.git/hooks/` directory (error if not found)
  - [ ] Define hook content with sentinel comments:
    ```
    # --- docbot hook start ---
    if [ -d ".docbot" ]; then
        docbot update 2>&1 | tail -5
    fi
    # --- docbot hook end ---
    ```
  - [ ] If `post-commit` doesn't exist: create it with `#!/bin/sh\n` + hook content
  - [ ] If `post-commit` exists and already has docbot section: print "already installed", return
  - [ ] If `post-commit` exists without docbot section: append hook content
  - [ ] Set executable permission (chmod +x on non-Windows)
  - [ ] Return True on success
- [ ] Implement `uninstall_hook(repo_root: Path) -> bool`:
  - [ ] Read post-commit hook file
  - [ ] Find and remove content between sentinel comments (inclusive)
  - [ ] If remaining content is empty or shebang-only, delete the file
  - [ ] Return True on success, False if hook not found or no docbot section

#### Self-check before merge

- [ ] `get_current_commit()` returns valid hash in a git repo
- [ ] `get_current_commit()` returns None outside a git repo
- [ ] `get_changed_files()` returns correct file list after a commit
- [ ] `is_commit_reachable()` returns False for nonexistent commits
- [ ] `.docbot` in SKIP_DIRS -- scanner ignores `.docbot/` directory
- [ ] `run_async()` still works identically after refactor (backward compat)
- [ ] `generate_async()` produces same output as `run_async()` but in `.docbot/`
- [ ] `generate_async()` writes state.json with correct commit hash and scope_file_map
- [ ] `update_async()` only re-explores affected scopes (verify via console output / tracker)
- [ ] `update_async()` falls back to generate when state is invalid
- [ ] `install_hook()` creates working post-commit hook
- [ ] `uninstall_hook()` cleanly removes docbot section without affecting other hooks
- [ ] No import errors across the package

---

### Dev C -- Renderer & Serve Adaptation

**Branch:** `phase3/renderer-serve`
**Owned files:** `renderer.py`, `server.py`

#### Renderer Refactor (`src/docbot/renderer.py`)

- [ ] Extract `render_scope_doc(scope, index, out_dir, llm_client)`:
  - [ ] Generates single scope markdown doc at `out_dir/docs/modules/<scope_id>.generated.md`
  - [ ] If `llm_client` provided: use LLM to write narrative doc
  - [ ] If no LLM: use template fallback
  - [ ] Returns the written file path
- [ ] Extract `render_readme(index, out_dir, llm_client)`:
  - [ ] Generates `out_dir/docs/README.generated.md`
  - [ ] LLM or template fallback
  - [ ] Returns file path
- [ ] Extract `render_architecture(index, out_dir, llm_client)`:
  - [ ] Generates `out_dir/docs/architecture.generated.md`
  - [ ] LLM or template fallback
  - [ ] Returns file path
- [ ] Extract `render_api_reference(index, out_dir)`:
  - [ ] Generates `out_dir/docs/api.generated.md`
  - [ ] Template-only (no LLM needed)
  - [ ] Returns file path
- [ ] Extract `render_html_report(index, out_dir)`:
  - [ ] Generates `out_dir/index.html`
  - [ ] Returns file path
- [ ] Refactor existing `render()` to call all five individual functions
- [ ] Refactor existing `render_with_llm()` to call all five individual functions in parallel
- [ ] Verify: `render()` and `render_with_llm()` produce identical output to before refactor

#### Serve Adaptation (`src/docbot/server.py`)

- [ ] Import `find_docbot_root` from `project.py`
- [ ] When no explicit `run_dir` provided:
  - [ ] Call `find_docbot_root(Path.cwd())`
  - [ ] If found, use `.docbot/` as run_dir
  - [ ] If not found, fall back to current behavior (require explicit path)
- [ ] Update help text to mention `.docbot/` default behavior

#### Self-check before merge

- [ ] `render()` produces identical output to before refactor (regression test)
- [ ] `render_with_llm()` produces identical output to before refactor
- [ ] `render_scope_doc()` works standalone for a single scope
- [ ] `render_readme()` works standalone
- [ ] `render_architecture()` works standalone
- [ ] `render_api_reference()` works standalone
- [ ] `render_html_report()` works standalone
- [ ] `serve` defaults to `.docbot/` when present
- [ ] `serve` with explicit path still works
- [ ] No import errors across the package

---

### Phase 3 Integration

**Branch:** `phase3/integration`
**Owner:** Dev A or Dev B (whoever is available first)

After all three Phase 3 branches merge to master:

- [ ] Verify `docbot init` creates valid `.docbot/`
- [ ] Verify `docbot generate` runs full pipeline into `.docbot/`
- [ ] Verify `docbot status` shows correct state after generate
- [ ] Make a code change, commit
- [ ] Verify `docbot update` only re-processes affected scopes
- [ ] Verify `docbot status` reflects the update
- [ ] Verify `docbot serve` loads webapp from `.docbot/`
- [ ] Verify `docbot hook install` creates working post-commit hook
- [ ] Verify committing auto-triggers `docbot update` via hook
- [ ] Verify `docbot hook uninstall` removes hook cleanly
- [ ] Verify `docbot run` works as alias for `docbot generate`
- [ ] Verify `docbot config` read/write works
- [ ] Verify `git status` only shows `.docbot/config.toml` as trackable
- [ ] Test on a Python project (regression)
- [ ] Test on a TypeScript project
- [ ] Test on a mixed-language project

---

### Phase 3 Quick Reference: who owns what

| File                          | Owner (Phase 3) |
| ----------------------------- | ---------------- |
| `cli.py`                      | Dev A            |
| `models.py`                   | Dev A            |
| `project.py` (new)            | Dev A            |
| `pyproject.toml`              | Dev A            |
| `git_utils.py` (new)          | Dev B            |
| `orchestrator.py`             | Dev B            |
| `hooks.py` (new)              | Dev B            |
| `scanner.py`                  | Dev B            |
| `renderer.py`                 | Dev C            |
| `server.py`                   | Dev C            |
