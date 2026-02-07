# docbot

**Auto-document any Python codebase.**

Scans your repo, extracts the AST, and generates a full documentation site: architecture diagrams, API references, and env var catalogs. Every generated line is traceable back to source code.

## Quick Start

1. **Install**

   ```bash
   git clone <repo-url> && cd docbot
   uv pip install -e .
   ```

2. **Configure**
   Create a `.env` file:

   ```bash
   OPENROUTER_KEY=sk-or-...
   ```

3. **Run**
   ```bash
   docbot ./my-project
   ```

## Options

| Flag                | Description                                |
| ------------------- | ------------------------------------------ |
| `--no-llm`          | Run local extraction only (free/fast).     |
| `--model <id>`      | Switch LLM model (default: Google Gemini). |
| `--concurrency <N>` | Parallel workers (default: 4).             |
| `--output <path>`   | Base directory for run output.             |

## How It Works

1. **Scan**: Finds source files and entrypoints.
2. **Plan**: Groups files into logical documentation scopes.
3. **Explore**: Extracts symbols, imports, and references (AST/Tree-sitter).
4. **Reduce**: Builds a cross-file dependency graph.
5. **Render**: Generates Markdown/HTML artifacts.

## Stack

- **Core**: Python 3.11+, Typer, Pydantic, AsyncIO.
- **AI**: OpenRouter API.
- **Webapp**: React + FastAPI (Coming Soon).

## Architecture

```mermaid
graph TD
    CLI --> Orchestrator
    Orchestrator --> Scanner
    Scanner --> ScanResult
    Orchestrator --> Planner
    Planner --> ScopePlans
    Orchestrator --> Explorer
    Explorer --> ScopeResults
    Orchestrator --> Reducer
    Reducer --> DocsIndex
    Orchestrator --> Renderer
    Renderer --> Output[Markdown + HTML]
```
