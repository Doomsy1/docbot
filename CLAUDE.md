# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

```bash
# Install (editable mode)
uv pip install -e .

# Run on a repo (requires OPENROUTER_KEY in .env or environment)
docbot /path/to/repo

# Key flags
docbot /path/to/repo -o ./output -j 8 -t 180 -m xiaomi/mimo-v2-flash
docbot /path/to/repo --no-llm          # template-only mode (no LLM calls)
docbot /path/to/repo --visualize       # open live D3.js pipeline visualization
```

Requires Python 3.11+. Configuration: `.env` file with `OPENROUTER_KEY=sk-or-...` (searched in cwd and parent directories).

## Tests

```bash
pytest tests/
```

No test suite exists yet — tests directory contains only `__init__.py`.

## Architecture

Five-stage async pipeline orchestrated by `orchestrator.py`:

```
SCAN → PLAN → EXPLORE (parallel) → REDUCE → RENDER (parallel)
```

1. **Scanner** (`scanner.py`) — walks repo, finds `.py` files, classifies entrypoints/packages
2. **Planner** (`planner.py`) — groups files into documentation scopes by directory; LLM refines groupings
3. **Explorer** (`explorer.py`) — per-scope AST extraction (functions, classes, imports, env vars, errors) run in parallel via `asyncio.Semaphore`; LLM enriches each scope with a narrative summary
4. **Reducer** (`reducer.py`) — merges all scope results into a `DocsIndex`, deduplicates, computes dependency edges from imports, LLM writes cross-scope analysis + Mermaid graph
5. **Renderer** (`renderer.py`) — generates per-scope markdown docs, README, architecture overview, API reference, and HTML report; all narrative docs are LLM-written in parallel

**LLM is central, not optional.** The `--no-llm` flag exists as a fallback but the real value comes from LLM-generated narratives at every stage. The LLM client (`llm.py`) is a minimal async wrapper around OpenRouter using only stdlib `urllib.request` + `asyncio.to_thread()`.

**Pipeline visualization** (`tracker.py`, `viz_server.py`, `_viz_html.py`) — thread-safe state tracker + stdlib HTTP server serving an embedded D3.js radial tree that polls `/state` every 400ms.

## Key Data Models (`models.py`)

- `Citation` — source location (file, line_start, line_end, symbol, snippet) — used for traceability throughout
- `ScopePlan` → `ScopeResult` — the core unit of work; a scope groups related files for documentation
- `DocsIndex` — the global merged output containing all scopes, symbols, env vars, edges, and LLM analysis
- `RunMeta` — execution statistics for a pipeline run

## Conventions

- All modules use `from __future__ import annotations` and Python 3.10+ union syntax (`str | None`)
- CPU-bound work (AST parsing, file I/O) runs via `asyncio.to_thread()`; concurrency controlled by `asyncio.Semaphore`
- LLM prompt strings are module-level constants prefixed with `_` (e.g., `_EXPLORER_PROMPT`, `_MERMAID_SYSTEM`)
- Per-file extraction failures are caught and recorded — they never kill scope or pipeline
- LLM failures gracefully degrade to template-based fallbacks
- Output goes to timestamped run directories under `./runs/`

## Roadmap Context

See `ROADMAP.md`, `TEAM_PLAN.md`, and `CHECKLIST.md` for the planned evolution:
- **Phase 1:** Multi-language support via tree-sitter (TS/JS, Go, Rust, Java) + LLM fallback extraction. New `src/docbot/extractors/` package with pluggable extractor architecture.
- **Phase 2:** Interactive webapp — FastAPI backend + React SPA with AI chat, interactive system graph (ReactFlow), guided tours, code viewer, dynamic Mermaid visualizations.
