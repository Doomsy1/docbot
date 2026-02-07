# Docbot Team Execution Plan — 3 Developers, Zero Merge Conflicts

## Principle

Every source file has exactly **one owner**. No file is touched by more than one developer. Dependencies between developers are managed through **interface contracts defined upfront** and a **branching strategy** that eliminates merge conflicts entirely.

---

## File Ownership Map

### Developer A — "Core Infrastructure"

Owns the foundation layer: data models, scanning, LLM client, and final integration wiring.

| File                         | Action                                                                                       |
| ---------------------------- | -------------------------------------------------------------------------------------------- |
| `src/docbot/models.py`       | Modify — add `SourceFile`, `FileExtraction`, update `ScanResult`, `ScopeResult`, `DocsIndex` |
| `src/docbot/scanner.py`      | Modify — generalize to multi-language file discovery                                         |
| `src/docbot/llm.py`          | Modify (minor) — no breaking changes, but owns if any tweaks needed                          |
| `src/docbot/__init__.py`     | Modify — update exports if needed                                                            |
| `src/docbot/orchestrator.py` | Modify — adapt to new scanner output, new explorer interface                                 |
| `src/docbot/cli.py`          | Modify — update help text, adapt to new pipeline                                             |
| `src/docbot/server.py`       | **Create** — FastAPI backend for webapp (moved from Dev C)                                   |
| `pyproject.toml`             | Modify — add tree-sitter dependencies                                                        |

### Developer B — "Extraction Engine"

Owns all extraction logic: the entire new extractors package and the explorer refactoring.

| File                                            | Action                                                         |
| ----------------------------------------------- | -------------------------------------------------------------- |
| `src/docbot/extractors/__init__.py`             | **Create** — package init, exports `get_extractor()` router    |
| `src/docbot/extractors/base.py`                 | **Create** — `Extractor` protocol + `FileExtraction` re-export |
| `src/docbot/extractors/python_extractor.py`     | **Create** — move existing AST logic from explorer.py here     |
| `src/docbot/extractors/treesitter_extractor.py` | **Create** — tree-sitter extraction for TS/JS, Go, Rust, Java  |
| `src/docbot/extractors/llm_extractor.py`        | **Create** — LLM-based fallback extractor                      |
| `src/docbot/explorer.py`                        | Modify — refactor to use `get_extractor()`, remove AST code    |
| `src/docbot/search.py`                          | **Create** — Semantic search index (BM25/Vector)               |

### Developer C — "Pipeline & Presentation"

Owns the downstream pipeline stages, existing viz system, and the webapp backend.

| File                       | Action                                                    |
| -------------------------- | --------------------------------------------------------- |
| `src/docbot/planner.py`    | Modify — generalize prompts, expand crosscutting patterns |
| `src/docbot/reducer.py`    | Modify — generalize edge computation + prompts            |
| `src/docbot/renderer.py`   | Modify — generalize all prompts/templates                 |
| `src/docbot/tracker.py`    | Modify (if needed for webapp)                             |
| `src/docbot/viz_server.py` | Modify (evolves into or is replaced by webapp server)     |
| `src/docbot/_viz_html.py`  | Modify (evolves into or is replaced by webapp)            |

### Developer D — "Frontend Experience"

Owns the React application and user interaction layer.

| File      | Action                                  |
| --------- | --------------------------------------- |
| `webapp/` | **Create** — entire React SPA directory |

### Overlap verification

```
Dev A: models.py, scanner.py, llm.py, __init__.py, orchestrator.py, cli.py, pyproject.toml, server.py (new)
Dev B: extractors/* (all new), explorer.py, search.py (new)
Dev C: planner.py, reducer.py, renderer.py, tracker.py, viz_server.py, _viz_html.py

Intersection: ∅ (empty set — zero shared files)
```

---

## Branching Strategy

```
master
  │
  ├── phase0/contracts          ← Dev A creates, all devs review
  │     (models.py only — the shared interface definitions)
  │
  │   After phase0 merges to master:
  │
  ├── phase1/core-infra         ← Dev A branches from master
  ├── phase1/extraction-engine  ← Dev B branches from master
  ├── phase1/pipeline-prompts   ← Dev C branches from master
  ├── phase1/webapp-frontend    ← Dev D branches from master (builds against mocks)
  │
  │   All 4 merge to master (no conflicts — different files):
  │
  ├── phase2/integration        ← Dev A branches from master
  ├── phase2/webapp-backend     ← Dev C branches from master
  ├── phase2/webapp-bind        ← Dev D branches from master (connects to real API)
```

### Merge order

1. `phase0/contracts` → master (must go first, everyone depends on it)
2. `phase1/core-infra`, `phase1/extraction-engine`, `phase1/pipeline-prompts` → master (any order, no conflicts)
3. `phase2/integration` → master (Dev A wires orchestrator + CLI)
4. `phase2/webapp-backend` → master
5. `phase2/webapp-frontend` → master

---

## Phase 0: Interface Contracts (Day 1 — All 3 Devs Together)

Before anyone writes production code, **Dev A writes the model contracts** and all 3 devs review and agree. This takes ~1 hour and eliminates all cross-developer ambiguity.

**Dev A writes these exact definitions in `models.py`:**

```python
# New model: represents a discovered source file
class SourceFile(BaseModel):
    path: str          # repo-relative path
    language: str      # "python", "typescript", "go", "rust", "java", etc.

# New model: output from any extractor
class FileExtraction(BaseModel):
    symbols: list[PublicSymbol] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    env_vars: list[EnvVar] = Field(default_factory=list)
    raised_errors: list[RaisedError] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

# Updated ScanResult (was Python-only, now universal)
@dataclass
class ScanResult:
    root: Path
    source_files: list[SourceFile] = field(default_factory=list)  # was py_files
    packages: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)            # NEW: detected languages

# Updated ScopeResult — add languages field
class ScopeResult(BaseModel):
    # ... existing fields unchanged ...
    languages: list[str] = Field(default_factory=list)  # NEW

# Updated DocsIndex — add languages field
class DocsIndex(BaseModel):
    # ... existing fields unchanged ...
    languages: list[str] = Field(default_factory=list)  # NEW
```

**Dev A also defines the Extractor protocol that Dev B will implement:**

```python
# This goes in extractors/base.py but the interface is agreed upon here
from typing import Protocol

class Extractor(Protocol):
    def extract_file(self, abs_path: Path, rel_path: str, language: str) -> FileExtraction: ...
```

**All 4 devs sign off before Phase 1 begins.** This branch (`phase0/contracts`) merges to master.

---

## Phase 1: Parallel Development (No Dependencies Between Devs)

All 4 developers branch from master (which now contains the agreed contracts) and work simultaneously. **No developer touches another developer's files.**

### Dev A: Core Infrastructure

**Branch:** `phase1/core-infra`

**Task 1 — Generalize the scanner** (`scanner.py`)

- Add `LANGUAGE_EXTENSIONS` mapping (extension → language name)
- Replace `.py`-only filter with multi-extension matching
- Return `source_files: list[SourceFile]` instead of `py_files: list[str]`
- Generalize entrypoint detection (language-aware patterns)
- Generalize package detection (per-language markers)
- Expand `SKIP_DIRS`
- Populate `languages` field with detected languages

**Task 2 — Update LLM client** (`llm.py`)

- Minor: increase `max_tokens` default if needed for extraction prompts
- Ensure `chat()` method supports the structured output patterns Dev B will need

**Task 3 — Update pyproject.toml**

- Add `tree-sitter` and grammar package dependencies
- Add webapp dependencies (`fastapi`, `uvicorn`, `sse-starlette`)

**Task 4 — Webapp Server Skeleton** (`server.py`)

- FastAPI app with placeholder endpoints
- Wire up to read a `DocsIndex` from a run directory
- Basic `/api/index`, `/api/scopes`, `/api/graph` endpoints

**Deliverable:** Scanner that finds source files in any language, returns `list[SourceFile]`. Server skeleton ready.

---

### Dev B: Extraction Engine

**Branch:** `phase1/extraction-engine`

**Task 1 — Create extractors package** (`src/docbot/extractors/`)

- `__init__.py` — exports `get_extractor(language: str) -> Extractor`
- `base.py` — `Extractor` protocol, re-exports `FileExtraction` from models

**Task 2 — Python extractor** (`extractors/python_extractor.py`)

- Move `_extract_file()`, `_signature()`, `_first_line_docstring()`, `_safe_unparse()`, `_ENV_RE` from `explorer.py`
- Wrap in a `PythonExtractor` class implementing the `Extractor` protocol
- Zero logic changes — just reorganization

**Task 3 — Tree-sitter extractor** (`extractors/treesitter_extractor.py`)

- `TreeSitterExtractor` class implementing `Extractor`
- Per-language query definitions for: TypeScript, JavaScript, Go, Rust, Java
- Each language extracts: functions, classes/structs/interfaces, imports, env var patterns, error throwing
- Returns `FileExtraction` with proper `Citation` line numbers

**Task 4 — LLM fallback extractor** (`extractors/llm_extractor.py`)

- `LLMExtractor` class implementing `Extractor`
- Takes an `LLMClient` instance
- Sends source + structured JSON extraction prompt to LLM
- Parses response into `FileExtraction`
- Handles truncation for large files

**Task 5 — Refactor explorer** (`explorer.py`)

- Remove all AST code (now in `python_extractor.py`)
- Remove `_ENV_RE` regex
- `explore_scope()` now calls `get_extractor(language).extract_file()` per file
- `enrich_scope_with_llm()` — update prompt to use dynamic language name instead of "Python"
- Keep `_build_source_snippets` as-is

**Task 6 — Semantic Search** (`search.py`)

- Implement `SearchIndex` class
- Simple TF-IDF or BM25 index over extracted symbols
- `search(query: str) -> list[Citation]`

**Deliverable:** Pluggable extraction router + Search Engine.

---

### Dev C: Pipeline & Presentation

**Branch:** `phase1/pipeline-prompts`

**Task 1 — Update planner** (`planner.py`)

- Expand `_CROSSCUTTING_RE`: add "utils", "helpers", "common", "shared", "types", "models"
- `_PLANNER_SYSTEM` and `_PLANNER_PROMPT`: replace "Python repository" with `{languages}` placeholder
- `build_plan()`: work with `source_files: list[SourceFile]` instead of `py_files`
- `refine_plan_with_llm()`: include detected languages in prompt

**Task 2 — Update reducer** (`reducer.py`)

- `_compute_scope_edges()`: generalize import resolution beyond Python dotted paths
  - Use file-path-based matching as primary strategy
  - Fall back to prefix matching for dotted imports
- `_ANALYSIS_SYSTEM/PROMPT`: replace "Python" with `{languages}`
- `_MERMAID_SYSTEM/PROMPT`: replace "Python" with `{languages}`
- Pass `languages` parameter through `reduce_with_llm()`

**Task 3 — Update renderer** (`renderer.py`)

- All LLM prompt strings: replace "Python repository/module" with dynamic language info
- Template fallbacks: "source files" instead of "Python files"
- `_render_index_html()`: show detected languages in the HTML report header
- Pass `languages` through all `_generate_*_llm()` functions

**Deliverable:** All prompts/templates language-agnostic, reducer handles multi-language imports.

---

### Dev D: Frontend Experience (Dev A owns Server)

**Branch:** `phase1/webapp-frontend`

**Task 1 — React frontend scaffold** (`webapp/`)

- Scaffold with Vite + React + Tailwind
- Build config: output to `webapp/dist/`

**Task 2 — UI Components & Pages**

- Interactive system graph (ReactFlow)
- Chat panel with Mermaid rendering
- Code viewer (Shiki/Prism.js)
- Guided tours UI
- Documentation browser

**Task 3 — Mock Data Integration**

- Create `src/mocks.ts` within webapp to simulate API responses (matching the `models.py` contract)
- Build the entire UI against these mocks so it's fully functional without the backend

**Deliverable:** Fully functional frontend running against mock data.

---

## Phase 2: Integration & Webapp

After all Phase 1 branches merge to master (in any order).

### Dev A: Integration Wiring

**Branch:** `phase2/integration`

**Task 1 — Update orchestrator** (`orchestrator.py`)

- Adapt `run_async()` to use `scan.source_files` instead of `scan.py_files`
- Console output: show detected languages and file counts per language
- Explorer step now uses the extraction router automatically (since Dev B updated `explorer.py`)
- Pass `languages` through to reducer and renderer
- Update "No Python files found" → "No source files found"

**Task 2 — Update CLI** (`cli.py`)

- Update help text: "Generate thorough documentation for a repository"
- Redefine `--no-llm`: tree-sitter/AST extraction still works, LLM enrichment skipped, unsupported languages get basic file listing only
- Add `docbot serve` subcommand (shell — calls Dev C's `server.py`)

**Task 3 — WebApi Implementation** (`server.py`)

- Implement full API endpoints: `/api/index`, `/api/scopes/{id}`, `/api/graph`, `/api/source/{path}`, `/api/search`, `/api/chat`, `/api/tours`
- Integrate Dev B's `SearchIndex`
- Integrate Dev C's `DocsIndex`

---

### Dev C: Webapp (Backend + Frontend)

**Branch:** `phase2/webapp`

**Task 1 — Evolve existing viz** (`tracker.py`, `viz_server.py`, `_viz_html.py`) (Dev A owns Server)

- Dev A owns `server.py` now.
- Either integrate the existing D3 pipeline viz into the new webapp, or deprecate in favor of the new system

**Task 2 — Connect Frontend** (Dev D assist)

- Ensure `webapp/dist` is correctly served by FastAPI (Dev A implements this in `server.py`, Dev C verifies)

**Deliverable:** `docbot serve` launches the real backend serving the real frontend.

---

### Dev D: Webapp Binding

**Branch:** `phase2/webapp-bind`

**Task 1 — Remove Mocks**

- Switch API client from `src/mocks.ts` to real `/api/*` endpoints
- Test end-to-end with Dev A's CLI and Dev C's server

**Deliverable:** Integrated Docbot application.

---

### Dev B: Phase 2 Role

Dev B is free after Phase 1. Options:

- **Add more tree-sitter grammars** (Kotlin, C#, Swift, Ruby) — all within their owned `extractors/` directory
- **Write tests** for the extraction layer — new `tests/` files (no conflict)
- **Help Dev C** with webapp features that don't touch Dev C's owned files (e.g., writing test fixtures, documentation)

---

## Communication Checkpoints

| When          | What                                  | Who           |
| ------------- | ------------------------------------- | ------------- |
| Day 1 start   | Phase 0: agree on model contracts     | All 4         |
| Phase 1 mid   | Quick sync: any interface surprises?  | All 4         |
| Phase 1 end   | All 4 branches ready to merge.        | All 4         |
| Phase 2 start | Dev A + C + D sync on integration     | Dev A + C + D |
| Phase 2 end   | Integration testing on real codebases | All 4         |

---

## Risk Mitigation

| Risk                                 | Mitigation                                                                                                                                           |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Models contract changes mid-flight   | Phase 0 must be thorough. If a change is truly needed, Dev A makes it in `models.py` and notifies others immediately — only Dev A touches that file. |
| Tree-sitter grammar issues           | Dev B can swap any language to the LLM fallback extractor as a temporary measure. The extraction router makes this a one-line change.                |
| Large file list in `pyproject.toml`  | Only Dev A touches this file. Dev B and C communicate dependency needs to Dev A who adds them.                                                       |
| `orchestrator.py` integration breaks | Dev A owns this and runs integration tests against the other devs' merged code. Merge Phase 1 first, then Phase 2 integration.                       |

---

## Summary

```
Phase 0 (1 hour):  All 4 devs agree on model contracts → merge to master
Phase 1 (parallel): 4 branches, 0 shared files, merge in any order
Phase 2 (parallel): Dev A wires integration, Dev C finishes backend, Dev D binds frontend
```

No file is ever touched by two developers. Period.

---

## Phase 3: Git-Integrated CLI

Transition docbot from a standalone doc generator into a git-aware developer tool with persistent
`.docbot/` project directory and incremental updates.

### Design Decisions

- CWD is the default target; optional `[path]` override on all commands
- Only `.docbot/config.toml` is git-tracked; rest ignored via `.docbot/.gitignore`
- `docbot init` creates folder/config only; `docbot generate` runs pipeline separately
- Git hooks opt-in via `docbot hook install`
- TOML config via `tomllib` (stdlib 3.11+); no new dependencies

---

### Phase 3 File Ownership Map

#### Dev A -- "CLI & Project Infrastructure"

Owns the CLI restructure, project scaffolding, and config system.

| File                          | Action                                                                  |
| ----------------------------- | ----------------------------------------------------------------------- |
| `src/docbot/cli.py`           | Modify -- restructure with all new subcommands (init, generate, update, |
|                               | status, config, hook install/uninstall, serve adaptation)               |
| `src/docbot/models.py`        | Modify -- add `ProjectState` and `DocbotConfig` models                  |
| `src/docbot/project.py`       | **Create** -- `.docbot/` init, `find_docbot_root()`, config/state I/O   |
| `pyproject.toml`              | Modify -- version bump, any new deps if needed                          |

#### Dev B -- "Git Integration & Incremental Pipeline"

Owns the git utilities, incremental update logic, and orchestrator refactor.

| File                          | Action                                                                  |
| ----------------------------- | ----------------------------------------------------------------------- |
| `src/docbot/git_utils.py`     | **Create** -- `get_current_commit()`, `get_changed_files()`,            |
|                               | `is_commit_reachable()`, `get_repo_root()`                              |
| `src/docbot/orchestrator.py`  | Modify -- add `generate_async()` and `update_async()` entry points,     |
|                               | refactor pipeline helpers for `.docbot/`-aware output                   |
| `src/docbot/hooks.py`         | **Create** -- `install_hook()`, `uninstall_hook()` for post-commit hook |
| `src/docbot/scanner.py`       | Modify -- add `.docbot` to `SKIP_DIRS`                                  |

#### Dev C -- "Renderer & Serve Adaptation"

Owns the renderer refactor for selective re-rendering and serve command adaptation.

| File                          | Action                                                                  |
| ----------------------------- | ----------------------------------------------------------------------- |
| `src/docbot/renderer.py`      | Modify -- expose individual render functions (`render_scope_doc()`,     |
|                               | `render_readme()`, `render_architecture()`, `render_api_reference()`,   |
|                               | `render_html_report()`) for selective re-rendering during updates       |
| `src/docbot/server.py`        | Modify -- adapt serve to default to `.docbot/` directory when no path   |
|                               | given; ensure `find_docbot_root()` integration works                    |

### Overlap Verification

```
Dev A: cli.py, models.py, project.py (new), pyproject.toml
Dev B: git_utils.py (new), orchestrator.py, hooks.py (new), scanner.py
Dev C: renderer.py, server.py

Intersection: empty set -- zero shared files
```

---

### Phase 3 Interface Contracts

Before parallel work begins, agree on these interfaces:

**`ProjectState` model** (Dev A writes in `models.py`, Dev B consumes in `orchestrator.py`):
```python
class ProjectState(BaseModel):
    """Persistent state tracking for the .docbot/ directory."""
    last_commit: str | None = None          # Git commit hash at last generate/update
    last_run_id: str | None = None          # Most recent run ID
    last_run_at: str | None = None          # ISO timestamp of last run
    scope_file_map: dict[str, list[str]] = {}  # scope_id -> [repo-relative file paths]
```

**`DocbotConfig` model** (Dev A writes in `models.py`, all devs consume):
```python
class DocbotConfig(BaseModel):
    """User configuration stored in .docbot/config.toml."""
    model: str = "xiaomi/mimo-v2-flash"
    concurrency: int = 4
    timeout: float = 120.0
    max_scopes: int = 20
    no_llm: bool = False
```

**`project.py` functions** (Dev A writes, Dev B and CLI consume):
```python
def init_project(path: Path) -> Path:
    """Create .docbot/ directory with default config.toml and .gitignore. Returns .docbot/ path."""

def find_docbot_root(start: Path) -> Path | None:
    """Walk up from start looking for .docbot/ directory. Returns its parent (the project root), or None."""

def load_config(docbot_dir: Path) -> DocbotConfig:
    """Read .docbot/config.toml and return DocbotConfig."""

def save_config(docbot_dir: Path, config: DocbotConfig) -> None:
    """Write DocbotConfig to .docbot/config.toml."""

def load_state(docbot_dir: Path) -> ProjectState:
    """Read .docbot/state.json. Returns empty ProjectState if file missing."""

def save_state(docbot_dir: Path, state: ProjectState) -> None:
    """Write ProjectState to .docbot/state.json."""
```

**`git_utils.py` functions** (Dev B writes, Dev B's orchestrator consumes):
```python
def get_current_commit(repo_root: Path) -> str | None:
    """Return HEAD commit hash, or None if no commits / not a git repo."""

def get_changed_files(repo_root: Path, since_commit: str) -> list[str]:
    """Return repo-relative paths changed between since_commit and HEAD."""

def is_commit_reachable(repo_root: Path, commit: str) -> bool:
    """Check if commit hash still exists in history (handles rebase/force-push)."""

def get_repo_root(start: Path) -> Path | None:
    """Return git repo root via `git rev-parse --show-toplevel`, or None."""
```

**Renderer individual functions** (Dev C exposes, Dev B's `update_async()` calls):
```python
async def render_scope_doc(scope: ScopeResult, index: DocsIndex, out_dir: Path, llm: LLMClient | None) -> Path:
    """Render a single scope's markdown doc. Returns written file path."""

async def render_readme(index: DocsIndex, out_dir: Path, llm: LLMClient | None) -> Path:
    """Render README.generated.md. Returns written file path."""

async def render_architecture(index: DocsIndex, out_dir: Path, llm: LLMClient | None) -> Path:
    """Render architecture.generated.md. Returns written file path."""

def render_api_reference(index: DocsIndex, out_dir: Path) -> Path:
    """Render api.generated.md (template-only, no LLM). Returns written file path."""

def render_html_report(index: DocsIndex, out_dir: Path) -> Path:
    """Render index.html report. Returns written file path."""
```

All devs sign off on these contracts before Phase 3 parallel work begins.

---

### Phase 3 Branching Strategy

```
master (Phase 1 + Phase 2 complete)
  |
  +-- phase3/contracts            <- Dev A creates models + project.py interfaces, all devs review
  |     (models.py, project.py stubs)
  |
  |   After phase3/contracts merges to master:
  |
  +-- phase3/cli-project          <- Dev A: CLI restructure + project.py implementation
  +-- phase3/git-pipeline         <- Dev B: git_utils.py + orchestrator refactor + hooks.py
  +-- phase3/renderer-serve       <- Dev C: renderer refactor + serve adaptation
  |
  |   All 3 merge to master (no conflicts -- different files):
  |
  +-- phase3/integration          <- Dev A or B: wire CLI commands to orchestrator, end-to-end test
```

### Merge Order

1. `phase3/contracts` -> master (models + stubs; everyone depends on it)
2. `phase3/cli-project`, `phase3/git-pipeline`, `phase3/renderer-serve` -> master (any order, no conflicts)
3. `phase3/integration` -> master (wires everything together, full end-to-end testing)

---

### Phase 3 Implementation Details

#### Dev A Tasks (CLI & Project Infrastructure)

**Task 1 -- Models** (`models.py`)
- Add `ProjectState` and `DocbotConfig` Pydantic models
- Follow existing conventions: `from __future__ import annotations`, Field defaults

**Task 2 -- Project module** (`project.py`)
- `init_project(path)`: validate git repo (`.git/` exists), create `.docbot/` with subdirs
  (`docs/`, `docs/modules/`, `scopes/`, `history/`), write default `config.toml`, write `.gitignore`
- `find_docbot_root(start)`: walk `start` and its parents looking for `.docbot/` dir
- `load_config` / `save_config`: use `tomllib` for reading, string formatting for writing
- `load_state` / `save_state`: JSON via Pydantic `model_dump_json()` / `model_validate_json()`

**Task 3 -- CLI restructure** (`cli.py`)
- Replace current `run` / `serve` with full subcommand set
- `init [path]`: call `init_project()`, print next steps
- `generate [path]`: find `.docbot/`, load config, merge CLI flag overrides, call
  `generate_async()` from orchestrator (Dev B builds this)
- `update`: find `.docbot/`, load config, call `update_async()` (Dev B builds this)
- `status`: find `.docbot/`, load state, run `get_changed_files()` (Dev B builds this),
  display last run info + changed file count + affected scope count
- `config [key] [value]`: no args = print all; 1 arg = print value; 2 args = set value
- `hook install` / `hook uninstall`: call `install_hook()` / `uninstall_hook()` (Dev B)
- `serve [path]`: default to `.docbot/` via `find_docbot_root()`, fall back to current behavior
- Keep `run` as hidden alias: `@app.command(hidden=True)` that calls `generate`

#### Dev B Tasks (Git Integration & Incremental Pipeline)

**Task 1 -- Git utilities** (`git_utils.py`)
- All functions use `subprocess.run()` with `cwd=repo_root`, `capture_output=True`, `text=True`
- Handle errors gracefully: return None/empty on failure, never raise
- `get_changed_files()` filters to only files (not directories) and normalizes to forward slashes

**Task 2 -- Scanner update** (`scanner.py`)
- Add `".docbot"` to `SKIP_DIRS` set (one-line change)

**Task 3 -- Orchestrator refactor** (`orchestrator.py`)
- Extract shared pipeline logic into internal helpers (e.g. `_run_scan`, `_run_plan`,
  `_run_explore`, `_run_reduce`, `_run_render`) that both `run_async` and `generate_async` use
- `generate_async(docbot_root, config, llm_client, tracker)`:
  - Infers `repo_path = docbot_root.parent`
  - Runs full 5-stage pipeline, outputs to `docbot_root` instead of `runs/<run_id>`
  - Saves per-scope results to `docbot_root / "scopes" / "<scope_id>.json"`
  - Saves docs_index.json, plan.json to `docbot_root`
  - Builds scope_file_map from the plan (scope_id -> paths)
  - Calls `save_state()` with current commit hash, run_id, scope_file_map
  - Saves RunMeta to `docbot_root / "history" / "<run_id>.json"`
- `update_async(docbot_root, config, llm_client, tracker)`:
  - Loads state via `load_state()`
  - Validates last_commit via `is_commit_reachable()`; falls back to generate if invalid
  - Gets changed files via `get_changed_files()`
  - Maps to affected scopes via `scope_file_map`
  - Handles new unscoped files (assign to nearest scope by directory path)
  - Re-explores affected scopes using existing `_explore_one()` with semaphore/timeout
  - Loads cached ScopeResult for unaffected scopes from `.docbot/scopes/`
  - Merges and calls reduce / reduce_with_llm
  - Calls renderer selectively (Dev C's individual render functions)
  - Updates state.json and saves run history
- Keep existing `run_async()` fully intact (backward compat)

**Task 4 -- Git hooks** (`hooks.py`)
- `install_hook(repo_root)`: create/append post-commit hook with sentinel comments
  ```bash
  # --- docbot hook start ---
  if [ -d ".docbot" ]; then
      docbot update 2>&1 | tail -5
  fi
  # --- docbot hook end ---
  ```
- `uninstall_hook(repo_root)`: remove content between sentinels, delete file if empty
- Handle permissions (chmod +x on Unix)

#### Dev C Tasks (Renderer & Serve Adaptation)

**Task 1 -- Renderer refactor** (`renderer.py`)
- Extract the existing monolithic `render()` / `render_with_llm()` into individual functions:
  - `render_scope_doc()` -- single scope markdown
  - `render_readme()` -- README.generated.md
  - `render_architecture()` -- architecture.generated.md
  - `render_api_reference()` -- api.generated.md (template-only)
  - `render_html_report()` -- index.html
- The existing `render()` and `render_with_llm()` become thin wrappers that call all five
- No behavior change for existing callers -- purely additive refactor

**Task 2 -- Serve adaptation** (`server.py`)
- When `run_dir` argument is not given, use `find_docbot_root(Path.cwd())` to locate `.docbot/`
- If `.docbot/` found and contains `docs_index.json`, serve from there
- If not found, fall back to current behavior (require explicit path)
- Update help text to reflect `.docbot/` default behavior

---

### Communication Checkpoints

| When            | What                                                       | Who     |
| --------------- | ---------------------------------------------------------- | ------- |
| Phase 3 start   | Agree on interface contracts (models, project.py, etc.)    | All     |
| Mid-sprint      | Quick sync: any interface surprises?                       | All     |
| Pre-merge       | All 3 branches ready, integration branch created           | All     |
| Post-integration| End-to-end testing on real repos                           | All     |

---

### Risk Mitigation

| Risk                                       | Mitigation                                                           |
| ------------------------------------------ | -------------------------------------------------------------------- |
| Model contract changes mid-flight          | Phase 3 contracts branch goes first; Dev A owns models.py            |
| Incremental update produces stale docs     | Always re-render cross-cutting docs; state.json tracks scope mapping |
| Git operations fail (not a repo, detached) | All git_utils functions return None/empty on failure; CLI validates   |
| Renderer refactor breaks existing behavior | Existing render/render_with_llm become wrappers; no logic changes    |
| Hook conflicts with existing git hooks     | Sentinel comments allow clean install/uninstall; never overwrite     |
