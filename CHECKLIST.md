# Docbot Development Checklist

> Single source of truth for development progress, file ownership, and task tracking.
> Check items off as you complete them. If swapping roles mid-sprint, the incoming dev reads
> the checked/unchecked state to know exactly where things stand.

---

## File Ownership Map

Every source file has exactly **one owner**. No file is touched by more than one developer during
a given phase. Dependencies between developers are managed through interface contracts defined upfront.

### Current ownership (Phase 3, updated for planned package reorganization)

| Current file                 | Planned location (after 3C reorg) | Owner  |
| ---------------------------- | --------------------------------- | ------ |
| `src/docbot/cli.py`          | `cli.py` (stays at top)           | Dev A  |
| `src/docbot/models.py`       | `models.py` (stays at top)        | Dev A  |
| `src/docbot/llm.py`          | `llm.py` (stays at top)           | Dev A  |
| `src/docbot/__init__.py`     | `__init__.py` (stays at top)      | Dev A  |
| `pyproject.toml`             | (root)                            | Dev A  |
| `src/docbot/project.py`      | `git/project.py`                  | Dev A  |
| `src/docbot/scanner.py`      | `pipeline/scanner.py`             | Dev B  |
| `src/docbot/orchestrator.py` | `pipeline/orchestrator.py`        | Dev B  |
| `src/docbot/git_utils.py`    | `git/utils.py`                    | Dev B  |
| `src/docbot/hooks.py`        | `git/hooks.py`                    | Dev B  |
| `src/docbot/extractors/*`    | `extractors/*` (already a package)| Dev B  |
| `src/docbot/explorer.py`     | `pipeline/explorer.py`            | Dev B  |
| `src/docbot/search.py`       | `web/search.py`                   | Dev B  |
| `src/docbot/planner.py`      | `pipeline/planner.py`             | Dev C  |
| `src/docbot/reducer.py`      | `pipeline/reducer.py`             | Dev C  |
| `src/docbot/renderer.py`     | `pipeline/renderer.py`            | Dev C  |
| `src/docbot/tracker.py`      | `pipeline/tracker.py`             | Dev C  |
| `src/docbot/server.py`       | `web/server.py`                   | Dev C  |
| `src/docbot/viz_server.py`   | `viz/viz_server.py`               | Dev C  |
| `src/docbot/_viz_html.py`    | `viz/_viz_html.py`                | Dev C  |
| `src/docbot/mock_viz.py`     | `viz/mock_viz.py`                 | Dev C  |
| `webapp/*`                   | `webapp/*`                        | Dev D  |
| `tests/*`                    | `tests/*`                         | Dev B  |

**New files (planned):**

| Planned file                 | Owner  | Phase   |
| ---------------------------- | ------ | ------- |
| `src/docbot/git/history.py`  | Dev B  | 3D      |
| `src/docbot/git/diff.py`     | Dev B  | 3E      |

---

## Phase 1: Multi-Language Support [COMPLETE]

All items complete. Tree-sitter + LLM fallback extraction implemented across Python, TypeScript,
JavaScript, Go, Rust, Java, Kotlin, C#, Swift, Ruby. Scanner generalized, explorer refactored,
planner/reducer/renderer prompts updated for dynamic language info, CLI/orchestrator wired.

<details>
<summary>Expand Phase 1 checklist (all checked)</summary>

### Phase 0: Interface Contracts -- Dev A

- [x] Add `SourceFile` model, `FileExtraction` model
- [x] Update `ScanResult`, `ScopeResult`, `DocsIndex` with language fields
- [x] Define `Extractor` protocol, review and merge

### Dev A -- Core Infrastructure

- [x] Scanner generalization (LANGUAGE_EXTENSIONS, entrypoint/package detection, SKIP_DIRS)
- [x] LLM client review, pyproject.toml deps, exports update
- [x] Webapp server skeleton (FastAPI with /api/index, /api/scopes, /api/graph, /api/search, /api/files, /api/fs)

### Dev B -- Extraction Engine

- [x] Extractors package (base.py, python_extractor.py, treesitter_extractor.py, llm_extractor.py)
- [x] Explorer refactor (remove AST code, use get_extractor())
- [x] Semantic search (SearchIndex class)

### Dev C -- Pipeline & Presentation

- [x] Planner updates (crosscutting patterns, dynamic language prompts)
- [x] Reducer updates (generalized edge computation, dynamic language prompts)
- [x] Renderer updates (dynamic language prompts/templates)

### Dev D -- Frontend Experience

- [x] React SPA scaffold (Vite + React + TypeScript + Tailwind)
- [x] Interactive system graph (ReactFlow), chat panel, code viewer, documentation browser

</details>

---

## Phase 2: Interactive Webapp [COMPLETE]

All items complete. FastAPI backend serves analyzed data + AI chat. React frontend with interactive
graph, chat panel, code viewer, guided tours, documentation browser. `docbot serve` launches the
full experience.

<details>
<summary>Expand Phase 2 checklist (all checked)</summary>

### Dev A -- Integration Wiring

- [x] Orchestrator adapted to source_files, languages pass-through
- [x] Server completion (source endpoint, search, chat, tours)
- [x] CLI updates (help text, serve subcommand, --no-llm behavior)

### Dev B -- Extended Coverage

- [x] Additional tree-sitter grammars (Kotlin, C#, Swift, Ruby)
- [x] Test suite (test_python_extractor, test_treesitter_extractor, test_llm_extractor, test_scanner, test_explorer)

### Dev C -- Webapp Backend

- [x] Serve static files from webapp/dist/

### Dev D -- Webapp Integration

- [x] Switch from mocks to real API endpoints
- [x] End-to-end testing, polish loading states
- [x] Legacy viz integration decision (marked as legacy)

</details>

---

## Phase 3: Git-Integrated CLI

> **Goal:** Transform docbot from a standalone doc generator into a git-aware CLI tool with
> persistent `.docbot/` project directory, incremental updates based on git diffs, documentation
> history with snapshots, before/after comparison, git lifecycle hooks, and a change-aware webapp.

> **Design decisions:** CWD default (optional path override), only config.toml git-tracked,
> init and generate are separate commands, git hooks opt-in via `docbot hook install`,
> last N snapshots for history (configurable, default 10), both explicit `docbot update` +
> optional hooks (post-commit and post-merge), change-aware chat via context injection into
> default `/api/chat` + dedicated `/api/changes` endpoint.

---

### 3A: Foundation (CLI + Project + Git Basics) [COMPLETE]

**Owner:** Dev A (CLI, models, project), Dev B (git_utils, hooks, scanner)

#### Models (`src/docbot/models.py`) -- Dev A

- [x] Add `ProjectState` model:
  - [x] `last_commit: str | None` -- git commit hash at last generate/update
  - [x] `last_run_id: str | None` -- most recent run ID
  - [x] `last_run_at: str | None` -- ISO timestamp of last run
  - [x] `scope_file_map: dict[str, list[str]]` -- scope_id -> repo-relative file paths
- [x] Add `DocbotConfig` model:
  - [x] `model: str` (default from llm.py)
  - [x] `concurrency: int = 4`
  - [x] `timeout: float = 120.0`
  - [x] `max_scopes: int = 20`
  - [x] `no_llm: bool = False`

#### Project Module (`src/docbot/project.py`) -- Dev A

- [x] Implement `init_project(path)`:
  - [x] Validate path is a git repo (check `.git/` exists)
  - [x] Create `.docbot/` directory with subdirs (`docs/`, `docs/modules/`, `scopes/`, `history/`)
  - [x] Write default `config.toml`
  - [x] Write `.gitignore` that ignores everything except `config.toml` and `.gitignore`
- [x] Implement `find_docbot_root(start)`:
  - [x] Walk start and parents looking for `.docbot/` directory
  - [x] Return the parent of `.docbot/` (the project root), or None
- [x] Implement `load_config(docbot_dir)` / `save_config(docbot_dir, config)`:
  - [x] TOML reading via `tomllib` (stdlib 3.11+)
  - [x] Simple string formatting for writing
- [x] Implement `load_state(docbot_dir)` / `save_state(docbot_dir, state)`:
  - [x] JSON via Pydantic `model_dump_json()` / `model_validate_json()`

#### CLI Restructure (`src/docbot/cli.py`) -- Dev A

- [x] `init [path]` command
- [x] `generate [path]` command (calls `run_async` currently; will call `generate_async` after 3B)
- [x] `update` command (stub -- falls back to full generate; will call `update_async` after 3B)
- [x] `status` command (shows last commit, changed files, affected scopes)
- [x] `config [key] [value]` command (view all / get one / set one)
- [x] `hook install` / `hook uninstall` subcommands
- [x] `serve [path]` adapted to default to `.docbot/` via `find_docbot_root()`
- [x] `run` kept as hidden alias for `generate`

#### Git Utilities (`src/docbot/git_utils.py`) -- Dev B

- [x] `get_current_commit(repo_root)` -- `git rev-parse HEAD`
- [x] `get_changed_files(repo_root, since_commit)` -- `git diff --name-only`
- [x] `is_commit_reachable(repo_root, commit)` -- `git cat-file -t`
- [x] `get_repo_root(start)` -- `git rev-parse --show-toplevel`

#### Git Hooks (`src/docbot/hooks.py`) -- Dev B

- [x] `install_hook(repo_root)` -- post-commit hook with sentinel comments
- [x] `uninstall_hook(repo_root)` -- remove docbot section, delete if empty

#### Scanner Update (`src/docbot/scanner.py`) -- Dev B

- [x] Add `".docbot"` to `SKIP_DIRS`

---

### 3B: Incremental Pipeline

**Owner:** Dev B (orchestrator, git integration), Dev C (renderer refactor)

> **Depends on:** 3A (complete)

#### Orchestrator Refactor (`src/docbot/orchestrator.py`) -- Dev B

- [ ] Extract pipeline stage helpers from `run_async()`:
  - [ ] `_run_scan(repo_path, tracker)` -> ScanResult
  - [ ] `_run_plan(scan, max_scopes, llm_client, tracker)` -> list[ScopePlan]
  - [ ] `_run_explore(plans, repo_path, sem, timeout, llm_client, tracker)` -> list[ScopeResult]
  - [ ] `_run_reduce(scope_results, repo_path, llm_client, tracker)` -> DocsIndex
  - [ ] `_run_render(docs_index, output_dir, llm_client, tracker)` -> list[Path]
- [ ] Refactor `run_async()` to call extracted helpers (no behavior change)
- [ ] Implement `generate_async(docbot_root, config, llm_client, tracker)`:
  - [ ] Infer `repo_path = docbot_root.parent`
  - [ ] Run full 5-stage pipeline, output to `docbot_root`
  - [ ] Save plan.json, per-scope results, docs_index.json
  - [ ] Build scope_file_map, call `save_state()` with current commit
  - [ ] Save RunMeta to history/
- [ ] Implement `update_async(docbot_root, config, llm_client, tracker)`:
  - [ ] Load state, validate last_commit via `is_commit_reachable()`
  - [ ] Fall back to `generate_async()` if commit unreachable
  - [ ] Get changed files, map to affected scopes via scope_file_map
  - [ ] Handle new unscoped files (assign to nearest scope by directory)
  - [ ] If >50% scopes affected, print suggestion to run `generate` instead
  - [ ] Re-explore affected scopes, load cached results for unaffected
  - [ ] Merge and re-run REDUCE
  - [ ] Call selective renderer functions (Dev C)
  - [ ] Update state.json and save run history

#### Renderer Refactor (`src/docbot/renderer.py`) -- Dev C

- [ ] Extract `render_scope_doc(scope, index, out_dir, llm_client)` -- single scope markdown
- [ ] Extract `render_readme(index, out_dir, llm_client)` -- README.generated.md
- [ ] Extract `render_architecture(index, out_dir, llm_client)` -- architecture.generated.md
- [ ] Extract `render_api_reference(index, out_dir)` -- api.generated.md (template-only)
- [ ] Extract `render_html_report(index, out_dir)` -- index.html
- [ ] Refactor `render()` and `render_with_llm()` to call individual functions (no behavior change)

#### CLI Update -- Dev A

- [ ] Update `generate` command to call `generate_async()` instead of `run_async()`
- [ ] Update `update` command to call `update_async()` instead of falling back to generate

#### Verification

- [ ] `run_async()` still works identically after refactor (backward compat)
- [ ] `generate_async()` produces same output as `run_async()` but writes to `.docbot/`
- [ ] `generate_async()` writes correct state.json with commit hash and scope_file_map
- [ ] `update_async()` only re-explores affected scopes
- [ ] `update_async()` falls back to generate when state is invalid
- [ ] Individual render functions work standalone

---

### 3C: Src Reorganization

**Owner:** All devs (coordinated, touching only owned files)

> **Depends on:** 3B (complete)

Move from 20 flat files in `src/docbot/` to organized packages.

#### Create package structure

- [ ] Create `src/docbot/pipeline/` package:
  - [ ] Move `scanner.py`, `planner.py`, `explorer.py`, `reducer.py`, `renderer.py`, `orchestrator.py`, `tracker.py`
- [ ] Create `src/docbot/git/` package:
  - [ ] Move `git_utils.py` -> `git/utils.py`
  - [ ] Move `hooks.py` -> `git/hooks.py`
  - [ ] Move `project.py` -> `git/project.py`
- [ ] Create `src/docbot/web/` package:
  - [ ] Move `server.py` -> `web/server.py`
  - [ ] Move `search.py` -> `web/search.py`
- [ ] Create `src/docbot/viz/` package:
  - [ ] Move `viz_server.py`, `_viz_html.py`, `mock_viz.py`
- [ ] Keep at top level: `cli.py`, `models.py`, `llm.py`, `__init__.py`

#### Update imports

- [ ] Update all internal imports across the codebase
- [ ] Update `cli.py` imports to use new package paths
- [ ] Update `pyproject.toml` entry points if needed
- [ ] Verify no import errors across the package

---

### 3D: Documentation Snapshots & History

**Owner:** Dev A (models), Dev B (history management)

> **Depends on:** 3B (complete -- needs generate_async/update_async to hook into)

#### Models (`src/docbot/models.py`) -- Dev A

- [ ] Add `DocSnapshot` model:
  - [ ] `commit_hash: str` -- git commit at snapshot time
  - [ ] `run_id: str` and `timestamp: str`
  - [ ] `scope_summaries: dict[str, ScopeSummary]` -- scope_id -> { file_count, symbol_count, summary_hash }
  - [ ] `graph_digest: str` -- hash of dependency graph edges
  - [ ] `doc_hashes: dict[str, str]` -- doc filename -> content hash
  - [ ] `stats: SnapshotStats` -- total files, scopes, symbols, edges
- [ ] Add `max_snapshots: int = 10` field to `DocbotConfig`

#### Snapshot Management (`src/docbot/git/history.py`) -- Dev B

- [ ] `save_snapshot(docbot_dir, docs_index, scope_results, run_id, commit)` -- create DocSnapshot + save scope results
- [ ] `load_snapshot(docbot_dir, run_id)` -- load a specific snapshot
- [ ] `list_snapshots(docbot_dir)` -- list available snapshots with metadata
- [ ] `prune_snapshots(docbot_dir, max_count)` -- remove oldest beyond limit
- [ ] Snapshot storage: `.docbot/history/<run_id>.json` (metadata) + `.docbot/history/<run_id>/` (scope results)

#### Pipeline Integration -- Dev B

- [ ] Hook `save_snapshot()` into `generate_async()` after state save
- [ ] Hook `save_snapshot()` into `update_async()` after state save
- [ ] Call `prune_snapshots()` after each save

---

### 3E: Before/After Comparison (`docbot diff`)

**Owner:** Dev A (CLI), Dev B (diff logic, models)

> **Depends on:** 3D (complete -- needs snapshots to compare)

#### Models (`src/docbot/models.py`) -- Dev A

- [ ] Add `ScopeModification` model:
  - [ ] `scope_id: str`
  - [ ] `added_files: list[str]`, `removed_files: list[str]`
  - [ ] `added_symbols: list[str]`, `removed_symbols: list[str]`
  - [ ] `summary_changed: bool`
- [ ] Add `DiffReport` model:
  - [ ] `added_scopes: list[str]` -- scope IDs that are new
  - [ ] `removed_scopes: list[str]` -- scope IDs that no longer exist
  - [ ] `modified_scopes: list[ScopeModification]`
  - [ ] `graph_changes: GraphDelta` -- new edges, removed edges, changed nodes
  - [ ] `stats_delta: StatsDelta` -- change in total files, scopes, symbols

#### Diff Logic (`src/docbot/git/diff.py`) -- Dev B

- [ ] `compute_diff(snapshot_from, snapshot_to)` -> DiffReport
- [ ] Compare scope lists (added/removed/modified)
- [ ] Per modified scope: compare file lists, symbol lists, doc hashes
- [ ] Compare graph edges (added/removed)
- [ ] Compute stats deltas

#### CLI Command -- Dev A

- [ ] Add `docbot diff [--from <commit-or-run>] [--to <commit-or-run>]` command
- [ ] Defaults: --from = previous snapshot, --to = current state
- [ ] Output: human-readable summary of what changed

---

### 3F: Git Lifecycle Hooks

**Owner:** Dev B (hooks expansion), Dev A (CLI flags)

> **Depends on:** 3B (complete -- needs working update_async)

#### Expand Hook Support (`src/docbot/hooks.py`) -- Dev B

- [ ] Add `install_post_merge_hook(repo_root)` -- same pattern as post-commit
- [ ] Update `install_hook()` to install both post-commit and post-merge by default
- [ ] Add `--commit-only` flag to install only post-commit
- [ ] Update `uninstall_hook()` to remove from both hook files

#### CLI Updates -- Dev A

- [ ] Update `docbot hook install` to accept `--commit-only` flag
- [ ] Update help text to describe post-merge behavior

#### Verification

- [ ] `docbot hook install` creates both post-commit and post-merge hooks
- [ ] `docbot hook install --commit-only` creates only post-commit
- [ ] `docbot hook uninstall` removes all docbot hooks
- [ ] `git pull` with post-merge hook triggers `docbot update`

---

### 3G: Change-Aware Webapp

**Owner:** Dev C (server endpoints), Dev D (frontend UI)

> **Depends on:** 3D (snapshots), 3E (diff)

#### API Endpoints (`src/docbot/server.py`) -- Dev C

- [ ] `GET /api/changes` -- returns DiffReport between current and previous snapshot
- [ ] `GET /api/changes?from=<run_id>&to=<run_id>` -- compare specific snapshots
- [ ] `GET /api/history` -- list available snapshots with metadata
- [ ] `GET /api/history/<run_id>` -- specific snapshot detail
- [ ] Update `POST /api/chat` system prompt to inject recent DiffReport when available

#### Webapp UI (`webapp/`) -- Dev D

- [ ] **Changes banner** -- summary banner when changes exist since last view
- [ ] **Architecture graph diff view** -- overlay showing added (green), removed (red), modified (yellow) nodes/edges
- [ ] **Scope diff panel** -- side-by-side or inline diff of scope documentation
- [ ] **Timeline view** -- visual timeline of snapshots, click to compare any two
- [ ] **Chat change context** -- suggested questions update when changes detected

#### Verification

- [ ] `/api/changes` returns correct DiffReport
- [ ] `/api/history` lists all snapshots
- [ ] Changes banner appears in webapp after an update
- [ ] Graph highlights changed nodes/edges
- [ ] Chat can answer "what changed?" questions with accurate references

---

## End-to-End Verification

After all Phase 3 sections complete:

- [ ] `docbot init` creates valid `.docbot/` with config.toml and .gitignore
- [ ] `docbot generate` runs full pipeline into `.docbot/`, saves state + snapshot
- [ ] `git status` only shows `.docbot/config.toml` as trackable
- [ ] `docbot status` shows correct state after generate
- [ ] Make a code change, commit
- [ ] `docbot update` only re-processes affected scopes, saves new snapshot
- [ ] `docbot diff` shows what changed between snapshots
- [ ] `docbot serve` loads webapp from `.docbot/` with changes banner
- [ ] Chat answers "what changed?" questions
- [ ] `docbot hook install` creates post-commit + post-merge hooks
- [ ] Committing auto-triggers `docbot update` via post-commit hook
- [ ] `git pull` auto-triggers `docbot update` via post-merge hook
- [ ] `docbot hook uninstall` removes all hooks cleanly
- [ ] `docbot run` works as alias for generate
- [ ] `docbot config` read/write works
- [ ] Test on a Python project (regression)
- [ ] Test on a TypeScript project
- [ ] Test on a mixed-language project

---

## Role Swap Guide

If a developer needs to take over another's work mid-sprint:

1. **Read their checklist above** -- checked items are done, unchecked items remain
2. **Check out their branch** -- all their work-in-progress is there
3. **Only touch their owned files** -- the file ownership table above is the source of truth
4. **Update this checklist** as you complete items
