# Docbot Evolution Plan

## Context

Docbot is an LLM-driven documentation generator that currently only works on Python codebases. The goal is to evolve
it into a universal tool that works on any codebase and provides an interactive AI-powered exploration experience --
optimized for developers onboarding onto unfamiliar projects.

Three major phases:

1. Multi-language support via tree-sitter parsing + LLM fallback for unsupported languages
2. Interactive webapp with AI chat, dynamic visualizations, interactive system graph, guided tours, and code
   navigation
3. Git-integrated CLI with persistent `.docbot/` project directory, incremental updates, documentation history,
   before/after comparison, and change-aware chatbot

Decisions made:

-   LLM is central and non-optional for enrichment/narratives
-   Tree-sitter + LLM fallback for structural extraction (fast/free for supported languages, universal coverage via LLM
    for the rest)
-   Keep Python's ast module (already built, zero dependencies) -- tree-sitter for TS/JS, Go, Rust, Java; LLM fallback
    for everything else
-   React SPA for the frontend
-   Backboard.io for LLM provider
-   Full experience for V1 webapp (chat + graph + dynamic viz + tours + code nav)

---

## Phase 1: Multi-Language Support (Tree-sitter + LLM Fallback) [COMPLETE]

### 1.1 Generalize the Scanner

File: src/docbot/scanner.py

Replace Python-only file discovery with universal source file detection.

Changes:

-   Add a LANGUAGE_EXTENSIONS mapping (extension -> language name) covering at minimum: Python, TypeScript, JavaScript,
    Go, Rust, Java, Kotlin, C, C++, Ruby, PHP, Swift, C#
-   Change the scan loop to match any known source extension instead of just .py
-   Rename py_files -> source_files in ScanResult (and add a language field per file, or store as tuples)
-   Generalize entrypoint detection with language-aware patterns:
    -   Python: main.py, app.py, cli.py, wsgi.py, asgi.py, **main**.py
    -   JS/TS: index.ts, index.js, app.ts, server.ts, main.ts
    -   Go: files containing func main()
    -   Rust: main.rs, lib.rs
    -   Java: files containing public static void main
    -   General: Dockerfile, docker-compose.yml, Makefile
-   Generalize package detection:
    -   Python: **init**.py
    -   JS/TS: package.json
    -   Go: directories with .go files
    -   Rust: Cargo.toml
    -   Java: directories with .java files
-   Expand SKIP_DIRS with: vendor, target, .cargo, bin, obj, .next, .nuxt, .svelte-kit, coverage, .gradle

### 1.2 Add Tree-sitter Extraction Layer

New file: src/docbot/extractors/**init**.py
New file: src/docbot/extractors/base.py
New file: src/docbot/extractors/python_extractor.py (wraps existing ast logic)
New file: src/docbot/extractors/treesitter_extractor.py
New file: src/docbot/extractors/llm_extractor.py

Create a pluggable extraction architecture with three backends:

Base extractor interface (base.py)

class Extractor(Protocol):
def extract_file(self, abs_path: Path, rel_path: str, language: str) -> FileExtraction:
"""Extract symbols, imports, env vars, errors from a single file."""

FileExtraction is a new dataclass holding: symbols: list[PublicSymbol], imports: list[str], env_vars: list[EnvVar],
raised_errors: list[RaisedError], citations: list[Citation]

Python extractor (python_extractor.py)

-   Move existing \_extract_file() logic from explorer.py here
-   Uses Python's built-in ast module -- zero dependencies, instant, already battle-tested
-   No changes to extraction logic, just reorganized

Tree-sitter extractor (treesitter_extractor.py)

-   Uses tree-sitter + language grammar packages
-   Phase 1 languages: TypeScript/JavaScript, Go, Rust, Java
-   Per-language query sets to extract:
    -   Functions/methods: name, signature (parameters + return type), docstring/comment
    -   Classes/structs/interfaces/enums: name, bases/implements, docstring
    -   Imports: module paths (normalized to dotted notation where possible)
    -   Env vars: patterns like process.env.X, os.Getenv("X"), std::env::var("X"), System.getenv("X")
    -   Error throwing: throw, panic!(), return err, etc.
-   Each language gets a query module (e.g. queries/typescript.py, queries/go.py) containing tree-sitter query strings
    and result-to-model mapping
-   Runtime: microseconds per file, same as Python AST

LLM extractor (llm_extractor.py)

-   Universal fallback for any language without a tree-sitter grammar
-   Sends file source + structured extraction prompt to LLM
-   Prompt asks for JSON matching existing model shapes:
    Given this {language} source file, extract as JSON:
-   public_symbols: [{name, kind, signature, docstring_first_line}]
-   imports: [list of imported modules/packages]
-   env_vars: [{name, default}]
-   raised_errors: [{expression}]
-   Token budget: truncate files >8K tokens, note truncation
-   Can batch small files together in a single call

Extraction router

-   get_extractor(language: str) -> Extractor
-   Python -> PythonExtractor
-   TypeScript, JavaScript, Go, Rust, Java -> TreeSitterExtractor(language)
-   Everything else -> LLMExtractor

### 1.3 Rework the Explorer

File: src/docbot/explorer.py

Refactor to use the new extraction layer.

Changes:

-   Replace \_extract_file() calls with get_extractor(language).extract_file()
-   explore_scope iterates over scope files, detects each file's language, routes to the right extractor
-   enrich_scope_with_llm stays mostly the same -- it takes the extracted data and generates LLM narratives
-   Remove ast import and all AST-specific code (moved to python_extractor.py)
-   Remove \_ENV_RE regex (moved to python_extractor.py)
-   Keep \_build_source_snippets for LLM enrichment context
-   Update \_EXPLORER_SYSTEM and \_EXPLORER_PROMPT -- replace "Python" with dynamic language info

### 1.4 Update Models

File: src/docbot/models.py

-   Add language: str field to ScopeResult (e.g. "python", "typescript", "go") -- or languages: list[str] if a scope
    spans multiple languages
-   Add languages: list[str] field to DocsIndex (all languages detected in repo)
-   Add SourceFile model: path: str, language: str
-   Update ScanResult: rename py_files -> source_files with type list[SourceFile]
-   Update PublicSymbol.kind docstring to include: "function", "class", "interface", "struct", "type", "enum", "trait",
    "method"
-   Add FileExtraction model for the extraction layer output

### 1.5 Update the Planner

File: src/docbot/planner.py

-   Expand \_CROSSCUTTING_RE patterns: add "utils", "helpers", "common", "shared", "types", "models"
-   Update \_PLANNER_SYSTEM and \_PLANNER_PROMPT -- replace "Python repository" with dynamic language info
-   Generalize build_plan to work with the new source_files field
-   Update refine_plan_with_llm prompt -- mention detected languages

### 1.6 Update the Reducer

File: src/docbot/reducer.py

-   \_compute_scope_edges: generalize import resolution
    -   Currently Python-specific (dotted path matching)
    -   For tree-sitter extracted imports: normalize to file paths where possible, fall back to prefix matching
    -   The LLM extractor already produces normalized imports
-   Update all prompt strings -- replace "Python" with detected languages
-   Pass language info into the Mermaid generation prompt

### 1.7 Update the Renderer

File: src/docbot/renderer.py

-   Update all LLM prompt strings -- replace "Python repository" with dynamic language info
-   Update template fallbacks: "source files" instead of "Python files"
-   HTML report template stays mostly the same

### 1.8 Update CLI + Orchestrator

Files: src/docbot/cli.py, src/docbot/orchestrator.py

CLI:

-   Update help text: "Generate thorough documentation for a repository" (drop "Python")
-   --no-llm flag: keep it, but it now means "no LLM enrichment" -- tree-sitter/AST extraction still works for supported
    languages, unsupported languages will have limited extraction (basic file listing only)
-   Update "No Python files found" -> "No source files found"

Orchestrator:

-   Adapt to new scanner output (source_files instead of py_files)
-   Console output: show detected languages and file counts per language
-   Explorer step uses the extraction router automatically

### 1.9 New Dependencies

pyproject.toml:

-   Add tree-sitter>=0.21 (the Python binding)
-   Add language grammar packages:
    -   tree-sitter-javascript
    -   tree-sitter-typescript
    -   tree-sitter-go
    -   tree-sitter-rust
    -   tree-sitter-java
-   Consider using tree-sitter-languages (bundles many grammars) as an alternative to individual packages

---

## Phase 2: Interactive Webapp [COMPLETE]

### 2.1 Backend (FastAPI)

New file: src/docbot/server.py

FastAPI app that serves the analyzed data and proxies AI chat.

API Endpoints:

-   GET /api/index -- full DocsIndex
-   GET /api/scopes -- list scopes with metadata
-   GET /api/scopes/{scope_id} -- scope detail (symbols, imports, citations)
-   GET /api/graph -- dependency graph as nodes + edges (for ReactFlow/D3)
-   GET /api/source/{file_path:path} -- source code of a file from the analyzed repo
-   GET /api/search?q=term -- search symbols, files, docs
-   GET /api/tours -- list AI-generated guided tours
-   GET /api/tours/{tour_id} -- specific tour steps
-   POST /api/chat -- send message to AI agent, SSE-streamed response
-   GET /api/docs/{scope_id} -- rendered markdown doc for a scope

AI Chat Agent:

-   System prompt includes serialized DocsIndex (scopes, symbols, edges, analysis)
-   On each user message, the agent can:
    -   Answer questions citing file:line
    -   Generate Mermaid diagrams inline (frontend renders them)
    -   Reference and link to specific scopes/symbols
-   Uses the existing LLMClient with chat() for multi-turn
-   Maintain conversation history per session (in-memory)

Tour Generation:

-   On first serve, generate guided tours via LLM:
    -   "Project Overview" -- high-level architecture walkthrough
    -   "Request Lifecycle" -- trace a request from entry to response (if applicable)
    -   "Getting Started" -- key files a new developer should read first
    -   Per-scope deep dives
-   Each tour = list of steps, each step = { title, explanation, file, line_start, line_end, optional_diagram }
-   Cache generated tours to disk alongside run output

### 2.2 Frontend (React SPA)

New directory: webapp/

React app built with Vite, served by the FastAPI backend in production.

Core Components:

1. Interactive System Graph (main view)

-   ReactFlow-based zoomable, pannable graph
-   Nodes = scopes (colored by type: entrypoint, cross-cutting, regular)
-   Edges = dependency relationships
-   Click a node -> sidebar shows scope detail (files, symbols, summary)
-   Drill down: click into a scope -> see internal modules/files as sub-nodes
-   Search bar: type a symbol/file name -> graph highlights relevant nodes
-   Filter controls: show only entrypoints, only a specific language, etc.

2. Chat Panel (right sidebar or bottom panel)

-   Message input with streaming responses
-   Responses render Mermaid diagrams inline
-   Citation links (file:line) are clickable -> opens code viewer
-   Conversation history within session
-   Suggested questions: "What does this project do?", "How does auth work?", "Where are the API routes?"

3. Code Viewer (modal or panel)

-   Syntax-highlighted source code (use Prism.js or Shiki)
-   Line numbers, scrollable to specific lines
-   Opened from citation links in chat or graph detail
-   Shows file path breadcrumb

4. Guided Tours (overlay/panel)

-   List of available tours on a "Tours" tab
-   Step-by-step walkthrough: previous/next navigation
-   Each step highlights a code region + shows explanation + optional diagram
-   Progress indicator

5. Documentation Browser (tab)

-   Browse rendered markdown docs (the existing generated docs)
-   Per-scope docs, architecture overview, API reference
-   Search within docs

6. Layout:

-   Left: navigation sidebar (scopes list, tours, docs)
-   Center: interactive graph (default) or code viewer or doc viewer
-   Right: chat panel (collapsible)

### 2.3 CLI Integration

File: src/docbot/cli.py

Add a new CLI command:

docbot serve [RUN_DIR_OR_REPO] [--port 8080]

-   If given a run directory -> serve that run's data immediately
-   If given a repo path -> run full analysis first, then serve
-   Opens browser automatically
-   Serves the React SPA + FastAPI backend on a single port

### 2.4 New Dependencies

pyproject.toml:

-   Add fastapi and uvicorn for the backend
-   Add sse-starlette for server-sent events (chat streaming)

webapp/package.json:

-   React + Vite
-   ReactFlow (interactive graph)
-   Mermaid (diagram rendering)
-   Prism.js or Shiki (syntax highlighting)
-   Tailwind CSS (styling)
-   A markdown renderer (react-markdown)

### 2.5 Build & Packaging

-   The React app builds to static files (webapp/dist/)
-   FastAPI serves these static files at /
-   The built webapp is included in the Python package (so pip install docbot includes the frontend)
-   Dev mode: Vite dev server proxies API calls to FastAPI

---

## Phase 3: Git-Integrated CLI

> **Progress:** Sections 3.1 (CLI restructure), 3.2 (.docbot/ directory), 3.3 (state tracking),
> 3.4 (config model), 3.6 (git utilities), 3.8 (hooks), and 3.9 (scanner update) are **implemented**.
> Remaining: 3.5 (incremental update logic), 3.7 (orchestrator refactor with generate_async/update_async),
> renderer refactor (individual render functions), and the new vision sections 3.10-3.14 below.

Transition docbot from a standalone documentation generator (`docbot run <repo>`) into a persistent,
git-aware developer tool. Docs live in a `.docbot/` project directory (like `.git/`), and incremental
updates re-process only scopes whose files changed since the last documented commit.

Decisions made:

-   CWD is the default target; all commands accept an optional `[path]` override
-   Only `.docbot/config.toml` is git-tracked; everything else is git-ignored via `.docbot/.gitignore`
-   `docbot init` creates the folder/config only; `docbot generate` runs the pipeline separately
-   Git hooks are opt-in via `docbot hook install`
-   Keep Typer for CLI (already a dependency, works well for subcommands)
-   TOML config uses `tomllib` (stdlib in 3.11+) for reading; simple string formatting for writing (no new deps)

### 3.1 CLI Restructure

Replace the current two-command CLI (`run`, `serve`) with a git-style subcommand interface.

New commands:

| Command                       | Description                                                           |
| ----------------------------- | --------------------------------------------------------------------- |
| `docbot init [path]`          | Create `.docbot/` directory with config.toml and .gitignore           |
| `docbot generate [path]`      | Full documentation generation, output to `.docbot/`                   |
| `docbot update`               | Incremental update -- only re-process scopes with files changed since |
|                               | the last documented commit                                            |
| `docbot status`               | Show doc state: last run, last commit, changed files, affected scopes |
| `docbot serve [path]`         | Launch webapp against `.docbot/` (defaults to cwd's .docbot/)         |
| `docbot config [key] [value]` | View all config (no args), get one value, or set a value              |
| `docbot hook install`         | Install post-commit git hook that runs `docbot update`                |
| `docbot hook uninstall`       | Remove the docbot post-commit hook                                    |

`docbot run` is kept as a hidden alias for `docbot generate` for backward compatibility.

All commands that need an initialized project use `find_docbot_root()` which walks up from cwd (or
the given path) looking for a `.docbot/` directory, similar to how git finds `.git/`.

CLI flags on `generate` (carried over from current `run` command):

-   `--concurrency / -j` (default from config)
-   `--timeout / -t` (default from config)
-   `--model / -m` (default from config)
-   `--max-scopes` (default from config)
-   `--no-llm` (default from config)
-   `--visualize / --viz` (open live D3.js visualization)

File: src/docbot/cli.py

### 3.2 The `.docbot/` Directory

Replaces the `runs/` output model. Instead of timestamped run directories, docs live persistently
in `.docbot/`.

```
.docbot/
  config.toml              # User configuration (git-tracked)
  .gitignore               # Ignores everything except config.toml
  state.json               # Tracking state (last commit, scope-file mapping)
  docs_index.json          # Current full DocsIndex
  search_index.json        # BM25 search index
  plan.json                # Current scope plan (array of ScopePlan)
  index.html               # Interactive HTML report
  docs/                    # Generated markdown documentation
    README.generated.md
    architecture.generated.md
    api.generated.md
    modules/
      <scope_id>.generated.md
  scopes/                  # Individual ScopeResult JSON (needed for incremental updates)
    <scope_id>.json
  history/                 # RunMeta for each run
    <run_id>.json
```

The `.docbot/.gitignore` contains:

```
# Everything ignored except config
*
!config.toml
!.gitignore
```

Initialization (`docbot init`):

-   Validates target is a git repo (checks for `.git/`)
-   Creates `.docbot/` directory
-   Writes default `config.toml`
-   Writes `.gitignore`
-   Does NOT run the pipeline -- prints instruction to run `docbot generate`

New file: src/docbot/project.py -- contains `init_project()`, `find_docbot_root()`,
`load_config()`, `save_config()`, `load_state()`, `save_state()`

### 3.3 Project State Tracking

`.docbot/state.json` tracks the relationship between git history and documentation state.

New model (`ProjectState` in models.py):

```python
class ProjectState(BaseModel):
    """Persistent state tracking for the .docbot/ directory."""
    last_commit: str | None = None          # Git commit hash at last generate/update
    last_run_id: str | None = None          # Most recent run ID
    last_run_at: str | None = None          # ISO timestamp of last run
    scope_file_map: dict[str, list[str]] = {}  # scope_id -> list of repo-relative file paths
```

`scope_file_map` is the key data structure for incremental updates. After a full `generate`, it
records which files belong to which scope. On `update`, changed files are looked up in this map
to determine which scopes need re-processing.

`last_commit` is set to the output of `git rev-parse HEAD` at the end of each generate/update.

### 3.4 Configuration Model

`.docbot/config.toml` stores user preferences that persist across runs.

New model (`DocbotConfig` in models.py):

```python
class DocbotConfig(BaseModel):
    """User configuration stored in .docbot/config.toml."""
    model: str = "openai/gpt-oss-20b"
    concurrency: int = 4
    timeout: float = 120.0
    max_scopes: int = 20
    no_llm: bool = False
```

CLI flags override config values for that invocation (they do not persist unless `docbot config`
is used). Precedence: CLI flag > config.toml > default.

TOML reading uses `tomllib` (Python 3.11+ stdlib). Writing uses simple string formatting since
the config structure is flat -- no need for a `tomli-w` dependency.

### 3.5 Incremental Updates (`docbot update`)

The core git-integration feature. Algorithm:

1. Load `state.json` -- get `last_commit` and `scope_file_map`
2. Validate `last_commit` is reachable in git history (`git merge-base --is-ancestor`)
    - If not (rebase, force-push), print warning and fall back to full `docbot generate`
3. Run `git diff --name-only <last_commit>..HEAD` to get list of changed files
4. Map changed files to affected scopes using `scope_file_map`:
    - For each changed file, find which scope(s) contain it
    - Collect the set of affected scope IDs
5. Detect new files not in any scope:
    - If new source files exist that aren't in `scope_file_map`, they need scoping
    - If count is small, assign to closest scope by directory; if large, suggest `docbot generate`
6. For affected scopes only: re-run EXPLORE (extraction + LLM enrichment)
7. For unaffected scopes: load cached ScopeResult from `.docbot/scopes/<scope_id>.json`
8. Merge all scope results (fresh + cached) and re-run REDUCE (cross-scope analysis + Mermaid)
9. Re-run RENDER for:
    - Affected scope markdown docs
    - Cross-cutting docs (README, architecture, API ref) -- always re-rendered since they
      synthesize across scopes
10. Update `state.json`: new commit hash, updated scope_file_map, run metadata
11. Save run history to `.docbot/history/`

Edge cases:

-   Deleted files: remove from scope_file_map; re-explore scope if it still has other files;
    drop scope entirely if all its files are gone
-   Renamed files: git reports as delete + add; handled naturally by the above
-   If >50% of scopes affected, print suggestion to run `docbot generate` instead (but proceed
    if user chose `update`)
-   If `state.json` is missing or corrupted, fall back to full generate with a warning

Files: src/docbot/orchestrator.py (add `update_async()`), src/docbot/git_utils.py (new)

### 3.6 Git Utilities

New file: src/docbot/git_utils.py

Thin wrappers around git CLI commands using `subprocess.run()`:

```python
def get_current_commit(repo_root: Path) -> str | None:
    """Return HEAD commit hash, or None if not a git repo / no commits."""
    # git rev-parse HEAD

def get_changed_files(repo_root: Path, since_commit: str) -> list[str]:
    """Return repo-relative paths of files changed between since_commit and HEAD."""
    # git diff --name-only <since_commit>..HEAD

def is_commit_reachable(repo_root: Path, commit: str) -> bool:
    """Check if a commit hash still exists in the repository history."""
    # git cat-file -t <commit>

def get_repo_root(start: Path) -> Path | None:
    """Return the git repository root, or None if not inside a git repo."""
    # git rev-parse --show-toplevel
```

All functions accept `repo_root` so they can be called with `cwd=repo_root` in subprocess.
All handle subprocess errors gracefully (return None/empty rather than raising).

### 3.7 Orchestrator Refactor

File: src/docbot/orchestrator.py

The current `run_async()` stays intact for backward compatibility. Two new async entry points:

`generate_async(docbot_root: Path, config: DocbotConfig, ...)`:

-   Calls the same 5-stage pipeline (scan -> plan -> explore -> reduce -> render)
-   Outputs to `docbot_root` (the `.docbot/` directory) instead of a timestamped `runs/` subdir
-   After rendering, saves state.json with current commit hash and scope_file_map
-   Saves run history entry to `docbot_root / "history" / "<run_id>.json"`
-   The repo path is inferred from `docbot_root.parent` (since `.docbot/` is at repo root)

`update_async(docbot_root: Path, config: DocbotConfig, ...)`:

-   Implements the incremental algorithm from section 3.5
-   Loads state, computes diff, identifies affected scopes
-   Re-uses `_explore_one()` for affected scopes (already handles concurrency + timeout)
-   Loads cached results for unaffected scopes
-   Calls existing `reduce` / `reduce_with_llm` with merged results
-   Calls renderer selectively (only affected scope docs + cross-cutting)

Renderer changes (src/docbot/renderer.py):

-   Expose individual render functions so the update path can call them selectively:
    -   `render_scope_doc(scope_result, docs_index, output_dir, llm_client)` -- single scope
    -   `render_readme(docs_index, output_dir, llm_client)` -- README only
    -   `render_architecture(docs_index, output_dir, llm_client)` -- architecture doc only
    -   `render_api_reference(docs_index, output_dir)` -- API ref only
    -   `render_html_report(docs_index, output_dir)` -- HTML report only
-   The existing `render()` and `render_with_llm()` continue to call all of these (no breaking change)

### 3.8 Git Hooks

New file: src/docbot/hooks.py

`install_hook(repo_root: Path) -> bool`:

-   Locates `.git/hooks/` directory
-   If `post-commit` hook doesn't exist, creates it with docbot update call
-   If `post-commit` exists, appends docbot section with sentinel comments:
    ```bash
    # --- docbot hook start ---
    if [ -d ".docbot" ]; then
        docbot update 2>&1 | tail -5
    fi
    # --- docbot hook end ---
    ```
-   Makes the hook executable (`chmod +x` on Unix; on Windows, git handles this)
-   Returns True on success

`uninstall_hook(repo_root: Path) -> bool`:

-   Reads existing post-commit hook
-   Removes content between `# --- docbot hook start ---` and `# --- docbot hook end ---`
-   If hook file is now empty (or only has shebang), deletes it
-   Returns True on success

CLI commands:

-   `docbot hook install` -- calls `install_hook()`, confirms success
-   `docbot hook uninstall` -- calls `uninstall_hook()`, confirms removal

### 3.9 Scanner Update

File: src/docbot/scanner.py

Single change: add `".docbot"` to the `SKIP_DIRS` set so docbot never tries to document its own
output directory.

### 3.10 Documentation Snapshots & History

The `history/` directory (already created by init) stores point-in-time snapshots of documentation state.

**Snapshot model** (`DocSnapshot` in models.py):

-   `commit_hash` -- git commit at snapshot time
-   `run_id` and `timestamp`
-   `scope_summaries` -- dict of scope_id to { file_count, symbol_count, summary_hash }
-   `graph_digest` -- hash/summary of dependency graph edges
-   `doc_hashes` -- dict of doc filename to content hash (for quick diff detection)
-   `stats` -- total files, scopes, symbols, edges

On every `generate` or `update`, save a snapshot to `.docbot/history/<run_id>.json`. Maintain at most
N snapshots (configurable via `config.toml`, default 10). Oldest pruned automatically.

**Snapshot storage** in `.docbot/`:

```
.docbot/history/
  <run_id>.json          # DocSnapshot metadata
  <run_id>/              # Full scope results at that point (for deep diff)
    <scope_id>.json
```

Files: src/docbot/models.py (DocSnapshot model), src/docbot/git/history.py (snapshot management)

### 3.11 Before/After Comparison (`docbot diff`)

New CLI command: `docbot diff [--from <commit-or-run>] [--to <commit-or-run>]`

Defaults: `--from` = previous snapshot, `--to` = current state.

**DiffReport model** (in models.py):

-   `added_scopes` -- scopes that didn't exist before
-   `removed_scopes` -- scopes that no longer exist
-   `modified_scopes` -- scopes with changed files, symbols, or docs
    -   Per scope: `added_files`, `removed_files`, `added_symbols`, `removed_symbols`, `summary_changed: bool`
-   `graph_changes` -- new edges, removed edges, changed nodes
-   `stats_delta` -- change in total files, scopes, symbols

CLI output: human-readable summary of what changed. The webapp provides visual diff.

Files: src/docbot/models.py (DiffReport model), src/docbot/git/diff.py (comparison logic), src/docbot/cli.py (diff command)

### 3.12 Git Lifecycle Integration

Expand hook support beyond post-commit:

| Git event                      | Hook type     | Docbot behavior                                       |
| ------------------------------ | ------------- | ----------------------------------------------------- |
| `git commit`                   | post-commit   | Run `docbot update` (existing)                        |
| `git pull` / `git merge`       | post-merge    | Run `docbot update` against incoming changes          |
| `git checkout` (branch switch) | post-checkout | (future) Warn if docs are stale for the target branch |

`docbot hook install` installs both post-commit and post-merge hooks by default.
`docbot hook install --commit-only` installs only post-commit.
`docbot hook uninstall` removes all docbot hooks.

**Pull workflow DX:**

```
git pull                          # new commits arrive
  -> post-merge hook fires
  -> docbot update runs           # incremental update against pulled changes
  -> snapshot saved to history/
Developer runs: docbot serve
  -> webapp shows "Changes" banner: "3 scopes updated from latest pull"
  -> architecture graph highlights changed/new/removed nodes
  -> click "View Changes" to see before/after
  -> chat has change context: "What changed in the auth module?"
```

Files: src/docbot/hooks.py (expand to post-merge), src/docbot/cli.py (hook install flags)

### 3.13 Change-Aware Webapp

New webapp features for the comparison/change experience:

**API endpoints:**

-   `GET /api/changes` -- returns DiffReport between current and previous snapshot
-   `GET /api/changes?from=<run_id>&to=<run_id>` -- compare specific snapshots
-   `GET /api/history` -- list available snapshots with metadata
-   `GET /api/history/<run_id>` -- specific snapshot detail

**Webapp UI additions:**

-   **Changes banner** -- when changes exist since last view, show a banner with summary
-   **Architecture graph diff view** -- overlay mode showing added (green), removed (red), modified (yellow) nodes/edges on the dependency graph
-   **Scope diff panel** -- side-by-side or inline diff of scope documentation
-   **Timeline view** -- visual timeline of snapshots, click to compare any two points
-   **Chat change context** -- system prompt automatically includes recent DiffReport so the chatbot can answer questions about what changed and why

**Chat integration:**

-   Default `/api/chat` injects a "recent changes" section into the system prompt when a DiffReport exists
-   Chatbot can reference changes: "The auth module was updated because 3 files changed: ..."
-   Suggested questions update to include change-related prompts when changes are detected

Files: src/docbot/server.py (new endpoints), webapp/ (new UI components)

### 3.14 Src Package Reorganization

Current: 20 flat `.py` files in `src/docbot/`. Proposed structure:

```
src/docbot/
  __init__.py               # Package root
  cli.py                    # CLI entry point (stays at top -- Typer app)
  models.py                 # All data models (stays at top -- shared)
  llm.py                    # LLM client (stays at top -- cross-cutting)

  pipeline/                 # Core 5-stage documentation pipeline
    __init__.py
    scanner.py              # Stage 1: file discovery
    planner.py              # Stage 2: scope planning
    explorer.py             # Stage 3: per-scope extraction + enrichment
    reducer.py              # Stage 4: cross-scope analysis
    renderer.py             # Stage 5: doc generation
    orchestrator.py         # Pipeline coordinator
    tracker.py              # Pipeline state tracking

  extractors/               # Language-specific extraction (already a package)
    __init__.py
    base.py
    python_extractor.py
    treesitter_extractor.py
    llm_extractor.py

  git/                      # Git integration layer
    __init__.py
    utils.py                # was git_utils.py
    hooks.py                # Hook install/uninstall
    project.py              # .docbot/ directory management
    history.py              # NEW: snapshot management (save/load/prune/compare)
    diff.py                 # NEW: diff computation between snapshots

  web/                      # Web serving layer
    __init__.py
    server.py               # FastAPI app
    search.py               # Search index

  viz/                      # Pipeline visualization (legacy, may deprecate)
    __init__.py
    viz_server.py
    _viz_html.py
    mock_viz.py
```

**Rationale:**

-   `pipeline/` groups the 5-stage core that does the actual documentation work
-   `git/` groups everything related to git integration, project state, and history
-   `web/` groups the serving layer (FastAPI + search)
-   `viz/` isolates the legacy D3 pipeline viz (candidate for deprecation or folding into web/)
-   Top-level keeps only truly cross-cutting modules: cli.py, models.py, llm.py

**Import changes:** All internal imports update (e.g. `from docbot.pipeline.scanner import scan_repo`, `from docbot.git.project import find_docbot_root`). External API stays the same (CLI entry point unchanged).

### 3.15 Pipeline Visualization Replay

The D3.js radial tree visualization (`tracker.py`, `viz_server.py`, `_viz_html.py`) currently runs live
during pipeline execution and discards all state when the run completes. This section adds the ability
to record pipeline execution and replay it after the fact.

**Event recording:**

Extend `PipelineTracker` to record every state transition as a timestamped event:

```python
@dataclass
class PipelineEvent:
    timestamp: float          # seconds since pipeline start (monotonic)
    node_id: str
    event_type: str           # "add" | "state_change"
    # For "add" events:
    name: str | None
    parent_id: str | None
    # For "state_change" events:
    new_state: str            # AgentState value
    detail: str
```

Every `add_node()` and `set_state()` call appends an event with a relative timestamp. This is sufficient
to reconstruct the full visualization at any point in the run.

**Storage:**

Events are saved to `.docbot/history/<run_id>/pipeline_events.json` at the end of each `generate` or
`update` run. Format:

```json
{
  "run_id": "abc123",
  "total_duration": 45.2,
  "events": [
    {"t": 0.0, "type": "add", "node": "orchestrator", "name": "Orchestrator", "parent": null},
    {"t": 0.0, "type": "state", "node": "orchestrator", "state": "running", "detail": ""},
    {"t": 0.1, "type": "add", "node": "scanner", "name": "Scanner", "parent": "orchestrator"},
    {"t": 0.1, "type": "state", "node": "scanner", "state": "running", "detail": ""},
    {"t": 2.3, "type": "state", "node": "scanner", "state": "done", "detail": "12 files"},
    ...
  ]
}
```

**Replay UI:**

Extend the existing D3.js visualization with a replay mode. Instead of polling `/state`, the page
reconstructs node state from the event log and animates through the timeline.

Controls:

-   Play / Pause button
-   Speed selector: 1x, 2x, 4x, 8x (real-time multiplier)
-   Timeline scrubber: drag to jump to any point in the run
-   Step forward / back: advance one event at a time
-   Elapsed time display: shows current playback position vs. total duration

The replay reuses the same D3 radial tree rendering -- the only difference is the data source
(recorded events vs. live `/state` polling).

**CLI integration:**

`docbot replay [run_id]` -- open replay visualization for a specific past run.

-   If no run_id given, replay the most recent run
-   Starts a local HTTP server serving the replay HTML + event data at `/events`
-   Opens browser automatically

The webapp (`docbot serve`) can also include a "Replay" section showing past run visualizations
alongside the documentation.

**Implementation approach:**

1. Add event recording to `PipelineTracker` (in `tracker.py`):

    - Internal `_events: list[dict]` and `_start_time: float` (monotonic reference)
    - `add_node()` appends an "add" event; `set_state()` appends a "state" event
    - New `export_events() -> dict` returns `{"run_id": ..., "total_duration": ..., "events": [...]}`
    - `NoOpTracker` gets a no-op `export_events()` returning empty data

2. Save events at pipeline end (in `orchestrator.py`):

    - `generate_async()` and `update_async()` call `tracker.export_events()` and write to
      `.docbot/history/<run_id>/pipeline_events.json`

3. Replay server (in `viz_server.py`):

    - New `start_replay_server(events_path)` that serves:
        - `GET /` -- replay HTML page
        - `GET /events` -- the recorded event log as JSON

4. Replay HTML (in `_viz_html.py`):
    - New `REPLAY_HTML` constant (or mode flag in existing `VIZ_HTML`)
    - Same D3 radial tree code, but data comes from `/events` on load instead of polling `/state`
    - JavaScript event player: maintains a virtual clock, applies events up to current time,
      renders the reconstructed snapshot

Files: src/docbot/tracker.py (event recording), src/docbot/orchestrator.py (save events),
src/docbot/viz_server.py (replay server), src/docbot/\_viz_html.py (replay UI),
src/docbot/cli.py (replay command)

---

## Phase 3 Verification

-   `docbot init` in a git repo -- `.docbot/` created with config.toml and .gitignore
-   `docbot generate` -- full pipeline outputs to `.docbot/`, state.json saved with commit hash
-   `git status` -- only `.docbot/config.toml` appears as trackable
-   `docbot status` -- shows last documented commit, files changed since, affected scopes
-   Make a code change, commit, `docbot update` -- only affected scopes re-processed
-   `docbot serve` -- webapp loads from `.docbot/` by default
-   `docbot hook install` -- post-commit hook created; committing triggers auto-update
-   `docbot hook uninstall` -- hook removed cleanly
-   `docbot run` -- still works as alias for generate
-   `docbot config model` -- prints current model
-   `docbot config model openai/gpt-oss-20b` -- updates config.toml
-   `docbot diff` -- shows changes between last two snapshots
-   `git pull` with post-merge hook -- triggers automatic doc update + snapshot
-   `docbot serve` after pull -- webapp shows changes banner with scope diff
-   Chat answers "what changed?" questions with accurate references
-   `docbot replay` -- opens replay of most recent run with playback controls
-   `docbot replay <run_id>` -- replays a specific past run
-   Replay scrubber, speed control, and step-through all work correctly
-   Replay visualization matches what the live view showed during the original run

---

## Implementation Order

Given project priority (foundational features first, then vision features), execute in this order:

**Phase 1 -- Multi-Language Support** [COMPLETE]

1. Model updates (1.4)
2. Scanner generalization (1.1)
3. Extraction layer (1.2)
4. Explorer rework (1.3)
5. Planner updates (1.5)
6. Reducer updates (1.6)
7. Renderer updates (1.7)
8. CLI + orchestrator updates (1.8)
9. Test on non-Python codebases

**Phase 2 -- Interactive Webapp** [COMPLETE] 10. FastAPI backend (2.1) 11. React frontend (2.2) 12. CLI serve command (2.3) 13. Polish

**Phase 3 -- Git-Integrated CLI** [IN PROGRESS] 14. CLI restructure + project module + models (3.1-3.4) [DONE] 15. Git utilities (3.6) [DONE] 16. Git hooks (3.8) [DONE] 17. Scanner update (3.9) [DONE] 18. Incremental update logic (3.5) + orchestrator refactor (3.7) 19. Renderer refactor (individual render functions) 20. Src package reorganization (3.14) 21. Documentation snapshots & history (3.10) 22. Before/after comparison -- `docbot diff` (3.11) 23. Git lifecycle integration -- post-merge hooks (3.12) 24. Change-aware webapp -- API endpoints + UI (3.13) 25. Pipeline visualization replay (3.15)

---

## Verification

### Phase 1 Verification

-   Run docbot on a Python project -- same quality output as before (regression test)
-   Run on a TypeScript/JavaScript project -- meaningful docs via tree-sitter extraction
-   Run on a Go project -- same (tree-sitter)
-   Run on a Rust project -- same (tree-sitter)
-   Run on a Ruby project -- works via LLM fallback extractor
-   Run on a mixed-language monorepo -- handles all languages, shows languages in output

### Phase 2 Verification

-   docbot serve on a completed run -- webapp opens in browser
-   Interactive graph renders with correct nodes/edges, zoomable/clickable
-   Chat agent answers questions with accurate citations
-   Clicking a citation opens code viewer at the right line
-   Dynamic Mermaid diagrams render inline in chat
-   Guided tours step through the codebase correctly
-   Works on both small and large codebases without UI lag

### Phase 3 Verification

-   See Phase 3 Verification section above
