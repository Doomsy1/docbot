# Migration Notes: agents/ -> exploration/

## What Changed

The old `src/docbot/agents/` module has been replaced by
`src/docbot/exploration/` for new agent exploration runs.

## Why

The old system had several limitations:

1. **Fixed 3-tier hierarchy** (Scope -> File -> Symbol agents).
   The new system has a single generalized agent that adapts to
   any level of exploration via purpose/context injection.

2. **Regex-based tool parsing.** The old `loop.py` parsed tool calls
   from LLM output using regex + fallback JSON blocks. The new system
   uses LangGraph's built-in tool calling via `llm.bind_tools()`.

3. **Per-scope notepad isolation.** Each scope had its own `Notepad`
   instance, so agents exploring `auth/` could not see what `api/`
   agents discovered. The new `NotepadStore` is shared across all
   agents in a run.

4. **Sequential with planner.** Old agents ran inside the explorer
   stage after planning. The new system starts agent exploration
   immediately after SCAN, running in parallel with the standard
   pipeline.

5. **No live visualization.** The old system had no real-time
   streaming of agent activity. The new system uses SSE callbacks
   for live force-graph visualization.

## Old System (src/docbot/agents/)

```
agents/
  loop.py          -- core agent execution loop (regex tool parsing)
  scope_agent.py   -- top-level per-scope agent
  file_agent.py    -- mid-level per-file agent
  symbol_agent.py  -- leaf agent for individual symbols
  tools.py         -- tool definitions + executor
  notepad.py       -- per-scope notepad (not shared)
```

## New System (src/docbot/exploration/)

```
exploration/
  __init__.py    -- entry point: run_agent_exploration()
  graph.py       -- LangGraph StateGraph (single agent type)
  tools.py       -- @tool functions via factory pattern
  store.py       -- NotepadStore (shared, thread-safe)
  prompts.py     -- single adaptive system prompt
  callbacks.py   -- AsyncCallbackHandler for SSE
```

## Backward Compatibility

- `src/docbot/agents/` is NOT deleted. It remains for reference and
  for any code that still imports from it.
- A deprecation warning has been added to `agents/__init__.py`.
- The `use_agents` config flag now routes to the new exploration
  system via the orchestrator's parallel tracks.
- Old behavior (when `use_agents=False`) is completely unchanged.

## Config Changes

New fields in `DocbotConfig`:

| Field           | Default | Notes                              |
|-----------------|---------|------------------------------------|
| agent_max_depth | 8       | Replaces old agent_depth (was 2)   |
| agent_model     | None    | Optional separate model for agents |

Old fields still present for backward compatibility:

| Field                    | Status     |
|--------------------------|------------|
| agent_depth              | Kept       |
| agent_scope_max_parallel | Kept       |
