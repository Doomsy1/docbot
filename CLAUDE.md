# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

```bash
# Install (editable mode)
uv pip install -e .

# Git-integrated workflow (requires OPENROUTER_KEY in .env or environment)
docbot init /path/to/repo
docbot generate                        # full pipeline, output to .docbot/
docbot serve                           # launch interactive webapp

# Key flags on generate
docbot generate -j 8 -t 180 -m openai/gpt-oss-20b
docbot generate --no-llm               # template-only mode (no LLM calls)
docbot generate --visualize            # open live D3.js pipeline visualization

# Other commands
docbot update                          # incremental update (changed files only)
docbot status                          # show doc state vs. current git HEAD
docbot config model openai/gpt-oss-20b # view/set config
docbot hook install                    # auto-update on git commit
```

Requires Python 3.11+. Configuration: `.env` file with `OPENROUTER_KEY=sk-or-...` (searched in cwd and parent directories).

## Tests

```bash
pytest tests/
```

No test suite exists yet -- tests directory contains only `__init__.py`.

## Architecture

Five-stage async pipeline orchestrated by `orchestrator.py`:

```
SCAN -> PLAN -> EXPLORE (parallel) -> REDUCE -> RENDER (parallel)
```

1. **Scanner** (`scanner.py`) -- walks repo, finds source files across all languages, classifies entrypoints/packages
2. **Planner** (`planner.py`) -- groups files into documentation scopes by directory; LLM refines groupings
3. **Explorer** (`explorer.py`) -- per-scope extraction via tree-sitter (10 languages) or LLM fallback (everything else), run in parallel via `asyncio.Semaphore`; LLM enriches each scope with a narrative summary
4. **Reducer** (`reducer.py`) -- merges all scope results into a `DocsIndex`, deduplicates, computes dependency edges from imports, LLM writes cross-scope analysis + Mermaid graph
5. **Renderer** (`renderer.py`) -- generates per-scope markdown docs, README, architecture overview, API reference, and HTML report; all narrative docs are LLM-written in parallel

**Extraction layer** (`extractors/`) -- pluggable architecture with three backends:
- `python_extractor.py` -- Python's built-in `ast` module (zero deps)
- `treesitter_extractor.py` -- tree-sitter for TS/JS, Go, Rust, Java, Kotlin, C#, Swift, Ruby
- `llm_extractor.py` -- LLM-based extraction for any unsupported language

**LLM is central, not optional.** The `--no-llm` flag exists as a fallback but the real value comes from LLM-generated narratives at every stage. The LLM client (`llm.py`) is a minimal async wrapper around OpenRouter using only stdlib `urllib.request` + `asyncio.to_thread()`.

**Git integration** (`project.py`, `git_utils.py`, `hooks.py`) -- `.docbot/` project directory management, git diff tracking for incremental updates, post-commit hook support.

**Interactive webapp** (`server.py` + `webapp/`) -- FastAPI backend serving analyzed data + AI chat. React SPA with interactive system graph (ReactFlow), chat panel, code viewer, guided tours, documentation browser.

**Pipeline visualization** (`tracker.py`, `viz_server.py`, `_viz_html.py`) -- thread-safe state tracker + stdlib HTTP server serving an embedded D3.js radial tree that polls `/state` every 400ms.

## Key Data Models (`models.py`)

- `Citation` -- source location (file, line_start, line_end, symbol, snippet) -- used for traceability throughout
- `ScopePlan` -> `ScopeResult` -- the core unit of work; a scope groups related files for documentation
- `DocsIndex` -- the global merged output containing all scopes, symbols, env vars, edges, and LLM analysis
- `RunMeta` -- execution statistics for a pipeline run
- `ProjectState` -- persistent state tracking (last commit, scope-file map) stored in `.docbot/state.json`
- `DocbotConfig` -- user configuration (model, concurrency, timeout, etc.) stored in `.docbot/config.toml`

## Conventions

- All modules use `from __future__ import annotations` and Python 3.10+ union syntax (`str | None`)
- CPU-bound work (AST parsing, file I/O) runs via `asyncio.to_thread()`; concurrency controlled by `asyncio.Semaphore`
- LLM prompt strings are module-level constants prefixed with `_` (e.g., `_EXPLORER_PROMPT`, `_MERMAID_SYSTEM`)
- Per-file extraction failures are caught and recorded -- they never kill scope or pipeline
- LLM failures gracefully degrade to template-based fallbacks
- Output goes to `.docbot/` project directory (git-tracked config only; everything else gitignored)

## Roadmap Context

See `ROADMAP.md` and `CHECKLIST.md` for the planned evolution:
- **Phase 1:** Multi-language support via tree-sitter + LLM fallback extraction. [COMPLETE]
- **Phase 2:** Interactive webapp -- FastAPI backend + React SPA. [COMPLETE]
- **Phase 3:** Git-integrated CLI with `.docbot/` project directory, incremental updates, documentation snapshots/history, before/after comparison (`docbot diff`), git lifecycle hooks (post-merge), change-aware webapp, pipeline visualization replay, and src package reorganization. [IN PROGRESS]
