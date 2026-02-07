# docbot

Automatic documentation generator for Python repositories. Uses parallel AST exploration, map-reduce aggregation, and LLM-powered narrative generation via OpenRouter.

Point it at any Python codebase and get a full documentation suite: per-module docs, architecture overview with Mermaid diagrams, API reference, environment variable catalog, and an HTML report -- all traceable back to specific files and line numbers.

## Installation

Requires Python 3.11+.

```bash
git clone <repo-url> && cd docbot
uv pip install -e .
```

## Configuration

Create a `.env` file in the project root (or export directly):

```
OPENROUTER_KEY=sk-or-...
```

Without the key, docbot still works in template-only mode (AST extraction + structured output, no LLM narratives).

## Usage

```bash
docbot /path/to/repo
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output`, `-o` | `./runs` | Base directory for run output |
| `--max-scopes` | `20` | Maximum number of documentation scopes |
| `--concurrency`, `-j` | `4` | Maximum parallel explorer workers |
| `--timeout`, `-t` | `120.0` | Per-scope timeout in seconds |
| `--model`, `-m` | `google/gemini-2.5-flash-lite-preview-09-2025` | OpenRouter model ID |
| `--no-llm` | `false` | Skip LLM calls entirely |

### Examples

```bash
# Full run with LLM at every step
docbot ./my-project

# Use a different model
docbot ./my-project --model anthropic/claude-sonnet-4

# Template-only mode (no API calls)
docbot ./my-project --no-llm

# High concurrency for large repos
docbot ./my-project -j 8 --max-scopes 30
```

## Output

Each run creates a timestamped folder under `runs/`:

```
runs/<run_id>/
  plan.json                        # Scope plan (LLM-refined when available)
  docs_index.json                  # Merged index with all scope data
  run_meta.json                    # Run metadata and stats
  scopes/
    <scope_id>.json                # Per-scope structured extraction
  README.generated.md              # Project README
  index.html                       # HTML report with Mermaid architecture graph
  docs/
    architecture.generated.md      # Architecture overview + dependency diagram
    api.generated.md               # Public API reference
    modules/
      <scope_id>.generated.md      # Per-scope module documentation
```

## How It Works

The pipeline has five stages, each using the LLM when available:

1. **Scan** -- walks the repo finding all `*.py` files, packages, and entrypoints.
2. **Plan** -- groups files into documentation scopes (packages, entrypoints, cross-cutting concerns). LLM refines scope titles, notes, and groupings.
3. **Explore** -- parallel AST-based extraction per scope: public API symbols, environment variables, raise statements, imports, and citations. LLM generates rich per-scope summaries.
4. **Reduce** -- merges scope results into a single index. LLM writes cross-scope architectural analysis and generates a Mermaid dependency graph.
5. **Render** -- generates all markdown and HTML. LLM writes per-module docs, README, and architecture overview. All LLM calls in this stage run in parallel.

Every claim is traceable: citations include `file`, `line_start`/`line_end`, and `symbol`.

## Architecture

```
CLI (typer)
  |
  v
Orchestrator (async pipeline)
  |
  +-- Scanner -----> ScanResult
  +-- Planner -----> [ScopePlan, ...]       (+ LLM refinement)
  +-- Explorer ----> [ScopeResult, ...]     (parallel, + LLM summaries)
  +-- Reducer -----> DocsIndex              (+ LLM analysis & Mermaid)
  +-- Renderer ----> markdown + HTML        (parallel LLM doc generation)
```

## Dependencies

- **typer** -- CLI framework
- **pydantic** -- data models and serialization
- **rich** -- terminal output and progress bars
- Python stdlib (`ast`, `asyncio`, `urllib`, `pathlib`, `json`)
- OpenRouter API (optional, for LLM-powered generation)

## License

MIT
