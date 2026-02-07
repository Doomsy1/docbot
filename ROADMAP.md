Docbot Evolution Plan
                                                                                                                       
 Context                                                                                      

 Docbot is an LLM-driven documentation generator that currently only works on Python codebases. The goal is to evolve
 it into a universal tool that works on any codebase and provides an interactive AI-powered exploration experience —
 optimized for developers onboarding onto unfamiliar projects.

 Two major phases:
 1. Multi-language support via tree-sitter parsing + LLM fallback for unsupported languages
 2. Interactive webapp with AI chat, dynamic visualizations, interactive system graph, guided tours, and code
 navigation

 Decisions made:
 - LLM is central and non-optional for enrichment/narratives
 - Tree-sitter + LLM fallback for structural extraction (fast/free for supported languages, universal coverage via LLM
  for the rest)
 - Keep Python's ast module (already built, zero dependencies) — tree-sitter for TS/JS, Go, Rust, Java; LLM fallback
 for everything else
 - React SPA for the frontend
 - OpenRouter only for LLM provider
 - Full experience for V1 webapp (chat + graph + dynamic viz + tours + code nav)

 ---
 Phase 1: Multi-Language Support (Tree-sitter + LLM Fallback)

 1.1 Generalize the Scanner

 File: src/docbot/scanner.py

 Replace Python-only file discovery with universal source file detection.

 Changes:
 - Add a LANGUAGE_EXTENSIONS mapping (extension → language name) covering at minimum: Python, TypeScript, JavaScript,
 Go, Rust, Java, Kotlin, C, C++, Ruby, PHP, Swift, C#
 - Change the scan loop to match any known source extension instead of just .py
 - Rename py_files → source_files in ScanResult (and add a language field per file, or store as tuples)
 - Generalize entrypoint detection with language-aware patterns:
   - Python: main.py, app.py, cli.py, wsgi.py, asgi.py, __main__.py
   - JS/TS: index.ts, index.js, app.ts, server.ts, main.ts
   - Go: files containing func main()
   - Rust: main.rs, lib.rs
   - Java: files containing public static void main
   - General: Dockerfile, docker-compose.yml, Makefile
 - Generalize package detection:
   - Python: __init__.py
   - JS/TS: package.json
   - Go: directories with .go files
   - Rust: Cargo.toml
   - Java: directories with .java files
 - Expand SKIP_DIRS with: vendor, target, .cargo, bin, obj, .next, .nuxt, .svelte-kit, coverage, .gradle

 1.2 Add Tree-sitter Extraction Layer

 New file: src/docbot/extractors/__init__.py
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

 - Move existing _extract_file() logic from explorer.py here
 - Uses Python's built-in ast module — zero dependencies, instant, already battle-tested
 - No changes to extraction logic, just reorganized

 Tree-sitter extractor (treesitter_extractor.py)

 - Uses tree-sitter + language grammar packages
 - Phase 1 languages: TypeScript/JavaScript, Go, Rust, Java
 - Per-language query sets to extract:
   - Functions/methods: name, signature (parameters + return type), docstring/comment
   - Classes/structs/interfaces/enums: name, bases/implements, docstring
   - Imports: module paths (normalized to dotted notation where possible)
   - Env vars: patterns like process.env.X, os.Getenv("X"), std::env::var("X"), System.getenv("X")
   - Error throwing: throw, panic!(), return err, etc.
 - Each language gets a query module (e.g. queries/typescript.py, queries/go.py) containing tree-sitter query strings
 and result-to-model mapping
 - Runtime: microseconds per file, same as Python AST

 LLM extractor (llm_extractor.py)

 - Universal fallback for any language without a tree-sitter grammar
 - Sends file source + structured extraction prompt to LLM
 - Prompt asks for JSON matching existing model shapes:
 Given this {language} source file, extract as JSON:
 - public_symbols: [{name, kind, signature, docstring_first_line}]
 - imports: [list of imported modules/packages]
 - env_vars: [{name, default}]
 - raised_errors: [{expression}]
 - Token budget: truncate files >8K tokens, note truncation
 - Can batch small files together in a single call

 Extraction router

 - get_extractor(language: str) -> Extractor
 - Python → PythonExtractor
 - TypeScript, JavaScript, Go, Rust, Java → TreeSitterExtractor(language)
 - Everything else → LLMExtractor

 1.3 Rework the Explorer

 File: src/docbot/explorer.py

 Refactor to use the new extraction layer.

 Changes:
 - Replace _extract_file() calls with get_extractor(language).extract_file()
 - explore_scope iterates over scope files, detects each file's language, routes to the right extractor
 - enrich_scope_with_llm stays mostly the same — it takes the extracted data and generates LLM narratives
 - Remove ast import and all AST-specific code (moved to python_extractor.py)
 - Remove _ENV_RE regex (moved to python_extractor.py)
 - Keep _build_source_snippets for LLM enrichment context
 - Update _EXPLORER_SYSTEM and _EXPLORER_PROMPT — replace "Python" with dynamic language info

 1.4 Update Models

 File: src/docbot/models.py

 - Add language: str field to ScopeResult (e.g. "python", "typescript", "go") — or languages: list[str] if a scope
 spans multiple languages
 - Add languages: list[str] field to DocsIndex (all languages detected in repo)
 - Add SourceFile model: path: str, language: str
 - Update ScanResult: rename py_files → source_files with type list[SourceFile]
 - Update PublicSymbol.kind docstring to include: "function", "class", "interface", "struct", "type", "enum", "trait",
  "method"
 - Add FileExtraction model for the extraction layer output

 1.5 Update the Planner

 File: src/docbot/planner.py

 - Expand _CROSSCUTTING_RE patterns: add "utils", "helpers", "common", "shared", "types", "models"
 - Update _PLANNER_SYSTEM and _PLANNER_PROMPT — replace "Python repository" with dynamic language info
 - Generalize build_plan to work with the new source_files field
 - Update refine_plan_with_llm prompt — mention detected languages

 1.6 Update the Reducer

 File: src/docbot/reducer.py

 - _compute_scope_edges: generalize import resolution
   - Currently Python-specific (dotted path matching)
   - For tree-sitter extracted imports: normalize to file paths where possible, fall back to prefix matching
   - The LLM extractor already produces normalized imports
 - Update all prompt strings — replace "Python" with detected languages
 - Pass language info into the Mermaid generation prompt

 1.7 Update the Renderer

 File: src/docbot/renderer.py

 - Update all LLM prompt strings — replace "Python repository" with dynamic language info
 - Update template fallbacks: "source files" instead of "Python files"
 - HTML report template stays mostly the same

 1.8 Update CLI + Orchestrator

 Files: src/docbot/cli.py, src/docbot/orchestrator.py

 CLI:
 - Update help text: "Generate thorough documentation for a repository" (drop "Python")
 - --no-llm flag: keep it, but it now means "no LLM enrichment" — tree-sitter/AST extraction still works for supported
  languages, unsupported languages will have limited extraction (basic file listing only)
 - Update "No Python files found" → "No source files found"

 Orchestrator:
 - Adapt to new scanner output (source_files instead of py_files)
 - Console output: show detected languages and file counts per language
 - Explorer step uses the extraction router automatically

 1.9 New Dependencies

 pyproject.toml:
 - Add tree-sitter>=0.21 (the Python binding)
 - Add language grammar packages:
   - tree-sitter-javascript
   - tree-sitter-typescript
   - tree-sitter-go
   - tree-sitter-rust
   - tree-sitter-java
 - Consider using tree-sitter-languages (bundles many grammars) as an alternative to individual packages

 ---
 Phase 2: Interactive Webapp

 2.1 Backend (FastAPI)

 New file: src/docbot/server.py

 FastAPI app that serves the analyzed data and proxies AI chat.

 API Endpoints:
 - GET /api/index — full DocsIndex
 - GET /api/scopes — list scopes with metadata
 - GET /api/scopes/{scope_id} — scope detail (symbols, imports, citations)
 - GET /api/graph — dependency graph as nodes + edges (for ReactFlow/D3)
 - GET /api/source/{file_path:path} — source code of a file from the analyzed repo
 - GET /api/search?q=term — search symbols, files, docs
 - GET /api/tours — list AI-generated guided tours
 - GET /api/tours/{tour_id} — specific tour steps
 - POST /api/chat — send message to AI agent, SSE-streamed response
 - GET /api/docs/{scope_id} — rendered markdown doc for a scope

 AI Chat Agent:
 - System prompt includes serialized DocsIndex (scopes, symbols, edges, analysis)
 - On each user message, the agent can:
   - Answer questions citing file:line
   - Generate Mermaid diagrams inline (frontend renders them)
   - Reference and link to specific scopes/symbols
 - Uses the existing LLMClient with chat() for multi-turn
 - Maintain conversation history per session (in-memory)

 Tour Generation:
 - On first serve, generate guided tours via LLM:
   - "Project Overview" — high-level architecture walkthrough
   - "Request Lifecycle" — trace a request from entry to response (if applicable)
   - "Getting Started" — key files a new developer should read first
   - Per-scope deep dives
 - Each tour = list of steps, each step = { title, explanation, file, line_start, line_end, optional_diagram }
 - Cache generated tours to disk alongside run output

 2.2 Frontend (React SPA)

 New directory: webapp/

 React app built with Vite, served by the FastAPI backend in production.

 Core Components:

 1. Interactive System Graph (main view)
   - ReactFlow-based zoomable, pannable graph
   - Nodes = scopes (colored by type: entrypoint, cross-cutting, regular)
   - Edges = dependency relationships
   - Click a node → sidebar shows scope detail (files, symbols, summary)
   - Drill down: click into a scope → see internal modules/files as sub-nodes
   - Search bar: type a symbol/file name → graph highlights relevant nodes
   - Filter controls: show only entrypoints, only a specific language, etc.
 2. Chat Panel (right sidebar or bottom panel)
   - Message input with streaming responses
   - Responses render Mermaid diagrams inline
   - Citation links (file:line) are clickable → opens code viewer
   - Conversation history within session
   - Suggested questions: "What does this project do?", "How does auth work?", "Where are the API routes?"
 3. Code Viewer (modal or panel)
   - Syntax-highlighted source code (use Prism.js or Shiki)
   - Line numbers, scrollable to specific lines
   - Opened from citation links in chat or graph detail
   - Shows file path breadcrumb
 4. Guided Tours (overlay/panel)
   - List of available tours on a "Tours" tab
   - Step-by-step walkthrough: previous/next navigation
   - Each step highlights a code region + shows explanation + optional diagram
   - Progress indicator
 5. Documentation Browser (tab)
   - Browse rendered markdown docs (the existing generated docs)
   - Per-scope docs, architecture overview, API reference
   - Search within docs
 6. Layout:
   - Left: navigation sidebar (scopes list, tours, docs)
   - Center: interactive graph (default) or code viewer or doc viewer
   - Right: chat panel (collapsible)

 2.3 CLI Integration

 File: src/docbot/cli.py

 Add a new CLI command:

 docbot serve [RUN_DIR_OR_REPO] [--port 8080]

 - If given a run directory → serve that run's data immediately
 - If given a repo path → run full analysis first, then serve
 - Opens browser automatically
 - Serves the React SPA + FastAPI backend on a single port

 2.4 New Dependencies

 pyproject.toml:
 - Add fastapi and uvicorn for the backend
 - Add sse-starlette for server-sent events (chat streaming)

 webapp/package.json:
 - React + Vite
 - ReactFlow (interactive graph)
 - Mermaid (diagram rendering)
 - Prism.js or Shiki (syntax highlighting)
 - Tailwind CSS (styling)
 - A markdown renderer (react-markdown)

 2.5 Build & Packaging

 - The React app builds to static files (webapp/dist/)
 - FastAPI serves these static files at /
 - The built webapp is included in the Python package (so pip install docbot includes the frontend)
 - Dev mode: Vite dev server proxies API calls to FastAPI

 ---
 Implementation Order

 Given user priority (multi-lang first), execute in this order:

 1. Model updates (1.4) — data structures ready first
 2. Scanner generalization (1.1) — find files in any language
 3. Extraction layer (1.2) — Python extractor (refactored from existing code), tree-sitter extractor, LLM fallback
 extractor
 4. Explorer rework (1.3) — use new extraction layer
 5. Planner updates (1.5) — adapt to new scanner output
 6. Reducer updates (1.6) — generalize edge computation + prompts
 7. Renderer updates (1.7) — generalize prompts/templates
 8. CLI + orchestrator updates (1.8) — wire it all together
 9. Test on non-Python codebases — validate on TS, Go, Rust projects
 10. FastAPI backend (2.1) — serve analyzed data + chat API
 11. React frontend (2.2) — interactive graph, chat, code viewer, tours
 12. CLI serve command (2.3) — tie it together
 13. Polish — error handling, loading states, mobile responsiveness

 ---
 Verification

 Phase 1 Verification

 - Run docbot on a Python project → same quality output as before (regression test)
 - Run on a TypeScript/JavaScript project → meaningful docs via tree-sitter extraction
 - Run on a Go project → same (tree-sitter)
 - Run on a Rust project → same (tree-sitter)
 - Run on a Ruby project → works via LLM fallback extractor
 - Run on a mixed-language monorepo → handles all languages, shows languages in output

 Phase 2 Verification

 - docbot serve on a completed run → webapp opens in browser
 - Interactive graph renders with correct nodes/edges, zoomable/clickable
 - Chat agent answers questions with accurate citations
 - Clicking a citation opens code viewer at the right line
 - Dynamic Mermaid diagrams render inline in chat
 - Guided tours step through the codebase correctly
 - Works on both small and large codebases without UI lag