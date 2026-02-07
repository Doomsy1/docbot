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
