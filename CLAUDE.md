# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

```bash
# Install (editable mode)
uv pip install -e .

# Git-integrated workflow (requires BACKBOARD_API_KEY in .env or environment)
docbot init /path/to/repo
docbot generate                        # full pipeline, output to .docbot/
docbot serve                           # launch interactive webapp

# Key flags on generate
docbot generate -j 8 -t 180 -m openai/gpt-4o-mini
docbot generate --no-llm               # template-only mode (no LLM calls)
docbot generate --agents               # enable LangGraph agent exploration (parallel with standard)
docbot generate --agents --serve       # agents + live webapp visualization
docbot generate --agents --serve -p 9000  # custom port for live webapp

# Other commands
docbot update                          # incremental update (changed files only)
docbot status                          # show doc state vs. current git HEAD
docbot config model openai/gpt-4o-mini # view/set config
docbot hook install                    # auto-update on git commit
```

Requires Python 3.11+. Configuration: `.env` file with `BACKBOARD_API_KEY=...` (searched in cwd and parent directories).

## Tests

```bash
pytest tests/                    # all tests
pytest tests/test_scanner.py     # single file
pytest tests/test_scanner.py -k "test_name"  # single test
```

Test files: `test_scanner`, `test_explorer`, `test_python_extractor`, `test_treesitter_extractor`, `test_llm_extractor`, `test_agent_toolkit_parallel`, `test_llm_rate_control`, `test_planner_balancing`, `test_exploration_graph`.

## Architecture

Five-stage async pipeline orchestrated by `orchestrator.py`:

```
SCAN -> PLAN -> EXPLORE (parallel) -> REDUCE -> RENDER (parallel)
```

1. **Scanner** (`scanner.py`) -- walks repo, finds source files across all languages, classifies entrypoints/packages
2. **Planner** (`planner.py`) -- groups files into documentation scopes by directory; LLM refines groupings; estimates cost per scope and auto-splits/merges scopes to hit a target cost budget
3. **Explorer** (`explorer.py`) -- per-scope extraction via tree-sitter (10 languages) or LLM fallback (everything else), run in parallel via `asyncio.Semaphore`; LLM enriches each scope with a narrative summary. Optionally uses recursive agents (`--agents` flag) for deeper analysis
4. **Reducer** (`reducer.py`) -- merges all scope results into a `DocsIndex`, deduplicates, computes dependency edges from imports, LLM writes cross-scope analysis + Mermaid graph
5. **Renderer** (`renderer.py`) -- generates per-scope markdown docs, README, architecture overview, API reference, and HTML report; all narrative docs are LLM-written in parallel

**Extraction layer** (`extractors/`) -- pluggable architecture with three backends:

-   `python_extractor.py` -- Python's built-in `ast` module (zero deps)
-   `treesitter_extractor.py` -- tree-sitter for TS/JS, Go, Rust, Java, Kotlin, C#, Swift, Ruby
-   `llm_extractor.py` -- LLM-based extraction for any unsupported language

**Agent exploration** (`exploration/`) -- LangGraph-based recursive agent for deep code exploration (enabled via `--agents`). Runs in parallel with the standard pipeline after SCAN. See `docs/AGENT_ARCHITECTURE.md` for full details:

-   `graph.py` -- LangGraph StateGraph with ReAct loop (agent -> tools -> agent)
-   `tools.py` -- `@tool`-decorated functions: `read_file`, `list_directory`, `read_notepad`, `write_notepad`, `list_topics`, `delegate`, `finish`
-   `store.py` -- thread-safe `NotepadStore` shared across all agents (cross-branch knowledge sharing)
-   `prompts.py` -- single adaptive system prompt with `{purpose}` and `{context_packet}` slots
-   `callbacks.py` -- `AsyncCallbackHandler` bridging LangGraph events to SSE stream

**Legacy agent system** (`agents/`) -- deprecated, retained for reference. Superseded by `exploration/`.

**LLM client** (`llm.py`) -- minimal async wrapper around Backboard.io using only stdlib `urllib.request` + `asyncio.to_thread()`. Includes automatic retry with exponential backoff (default 4 retries), adaptive concurrency reduction during sustained failures, and a global concurrency semaphore (default 6 workers).

**Git integration** (`project.py`, `git_utils.py`, `hooks.py`) -- `.docbot/` project directory management, git diff tracking for incremental updates, post-commit hook support. `ProjectState` tracks `scope_perf_map` to inform future cost estimates from prior runs.

**Interactive webapp** (`server.py` + `webapp/`) -- FastAPI backend serving analyzed data + AI chat. React SPA with interactive system graph (ReactFlow), chat panel, code viewer, guided tours, documentation browser, and live agent exploration visualization.

**Pipeline visualization** (`tracker.py` + webapp Pipeline tab) -- thread-safe tracker emits timeline events and orchestrator persists them to `.docbot/history/<run_id>/pipeline_events.json`; FastAPI serves `/api/pipeline/runs` + `/api/pipeline/events`.

**Agent exploration visualization** (webapp Exploration tab) -- react-force-graph-2d live visualization of agent tree. SSE streaming via `/api/agent-stream`, with agent detail panel and notepad topic browser. Endpoints: `/api/agent-stream` (SSE), `/api/agent-state` (snapshot), `/api/notepad` (topics), `/api/notepad/{topic}` (entries).

## Key Data Models (`models.py`)

-   `Citation` -- source location (file, line_start, line_end, symbol, snippet) -- used for traceability throughout
-   `ScopePlan` -> `ScopeResult` -- the core unit of work; a scope groups related files for documentation. `ScopePlan` includes `estimated_cost`, `estimated_tokens`, and `bucket` fields for cost balancing
-   `DocsIndex` -- the global merged output containing all scopes, symbols, env vars, edges, and LLM analysis
-   `RunMeta` -- execution statistics for a pipeline run
-   `ProjectState` -- persistent state tracking (last commit, scope-file map, scope-perf-map) stored in `.docbot/state.json`
-   `DocbotConfig` -- user configuration stored in `.docbot/config.toml`; key fields: `model`, `concurrency`, `timeout`, `max_scopes`, `target_scope_cost`, `split_threshold`, `merge_threshold`, `use_agents`, `agent_depth`, `agent_max_depth`, `agent_model`, `agent_scope_max_parallel`, `llm_backoff_enabled`, `llm_backoff_max_retries`, `llm_adaptive_reduction_factor`
-   `NoteEntry` -- single note with content, author, timestamp, citation (used by agent notepad)
-   `DocSnapshot`, `ScopeSummary`, `SnapshotStats` -- documentation history/snapshots
-   `DiffReport`, `ScopeModification`, `GraphDelta`, `StatsDelta` -- before/after comparisons

## Conventions

-   All modules use `from __future__ import annotations` and Python 3.10+ union syntax (`str | None`)
-   CPU-bound work (AST parsing, file I/O) runs via `asyncio.to_thread()`; concurrency controlled by `asyncio.Semaphore`
-   LLM prompt strings are module-level constants prefixed with `_` (e.g., `_EXPLORER_PROMPT`, `_MERMAID_SYSTEM`)
-   Per-file extraction failures are caught and recorded -- they never kill scope or pipeline
-   LLM failures gracefully degrade to template-based fallbacks
-   Output goes to `.docbot/` project directory (git-tracked config only; everything else gitignored)
-   Agent system uses depth tracking to prevent infinite recursion; subagents are scheduled immediately but flushed in batch via `flush_subagents()`
-   Multiple levels of concurrency semaphores: global LLM workers, scope-level parallelism, and agent-level parallelism

## Roadmap Context

See `ROADMAP.md` and `CHECKLIST.md` for the planned evolution:

-   **Phase 1:** Multi-language support via tree-sitter + LLM fallback extraction. [COMPLETE]
-   **Phase 2:** Interactive webapp -- FastAPI backend + React SPA. [COMPLETE]
-   **Phase 3:** Git-integrated CLI with `.docbot/` project directory, incremental updates, documentation snapshots/history, before/after comparison (`docbot diff`), git lifecycle hooks (post-merge), change-aware webapp, pipeline visualization replay, and src package reorganization. [IN PROGRESS]
