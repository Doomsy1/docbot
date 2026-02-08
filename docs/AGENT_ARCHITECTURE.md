# Agent Exploration Architecture

This document describes the LangGraph-based agent exploration system
in `src/docbot/exploration/`. It is intended as a guide for future
Claude sessions working on this module.

## Overview

The exploration system uses a **single generalized recursive agent**
built on LangGraph. Unlike the older `agents/` system (which used a
3-tier hierarchy of Scope/File/Symbol agents with regex-based tool
parsing), the new system has one agent type that adapts its behavior
based on:

- **purpose** -- injected into the system prompt
- **context_packet** -- condensed knowledge from the parent agent
- **depth** -- how deep in the delegation tree this agent sits

## Module Map

```
src/docbot/exploration/
  __init__.py    -- entry point: run_agent_exploration()
  graph.py       -- LangGraph StateGraph definition (AgentState, ReAct loop)
  tools.py       -- @tool-decorated functions created by factory
  store.py       -- NotepadStore for cross-agent knowledge sharing
  prompts.py     -- system prompt template
  callbacks.py   -- AsyncCallbackHandler for SSE event streaming
```

## How the Agent Works

### State Schema (graph.py)

Every agent invocation carries an `AgentState` TypedDict:

| Field          | Type             | Purpose                                    |
|----------------|------------------|--------------------------------------------|
| messages       | list[BaseMessage] | Conversation history (append-only)         |
| agent_id       | str              | Unique ID for this agent instance          |
| parent_id      | str or None      | Parent agent's ID (None for root)          |
| purpose        | str              | Why this agent was spawned                 |
| context_packet | str              | Knowledge from parent                      |
| repo_root      | str              | Absolute path to the repository            |
| scope_files    | list[str]        | Files this agent should focus on           |
| depth          | int              | Current recursion depth (0 = root)         |
| max_depth      | int              | Max allowed depth                          |
| summary        | str              | Set by `finish` tool when agent completes  |

### ReAct Loop

```
[entry] --> agent_node (LLM + bound tools)
               |
          tool_calls? --yes--> tool_node --> agent_node (loop)
               |
              no / finish --> END
```

The graph is compiled once and reused. Each `delegate` call recursively
invokes the same graph with a new AgentState.

### Tools (tools.py)

Created by `create_tools()` factory which binds runtime state:

| Tool           | Description                                          |
|----------------|------------------------------------------------------|
| read_file      | Read a source file (12K char cap)                    |
| list_directory | List dir contents (filters noise)                    |
| read_notepad   | Read shared notepad topic                            |
| write_notepad  | Append to shared notepad topic                       |
| list_topics    | Browse all notepad topics                            |
| delegate       | Spawn child agent for a subdirectory/module          |
| finish         | Return findings to parent, end agent                 |

### NotepadStore (store.py)

Thread-safe in-memory store where agents record findings:

- Organized by topic keys using dot-notation (e.g. `architecture.layers`)
- Any agent can read/write any topic
- Emits events to asyncio.Queue for live visualization
- Serializable to JSON for persistence

### Event System (callbacks.py)

`AgentEventCallback` is a LangChain `AsyncCallbackHandler` that pushes
events to an `asyncio.Queue`:

- `llm_token` -- streamed tokens from the LLM
- `tool_start` / `tool_end` / `tool_error` -- tool lifecycle
- `agent_spawned` / `agent_finished` / `agent_error` -- agent lifecycle
- `notepad_created` / `notepad_write` -- notepad changes

The SSE endpoint drains this queue and forwards events to the browser.

## Integration with the Pipeline

The orchestrator runs two tracks in parallel after SCAN:

```
SCAN
  |
  +---> Standard Track (PLAN -> EXPLORE -> enrich)
  |
  +---> Agent Track (root agent -> delegates -> notepad filled)
  |
  v
MERGE (enrich scope results with notepad findings)
  |
  v
REDUCE -> RENDER
```

- Standard track produces structural data (symbols, imports, env vars)
- Agent track produces semantic understanding (architecture, patterns,
  design decisions, cross-cutting concerns)
- After both complete, scope summaries are enriched with relevant
  notepad findings before reduce/render

## Configuration

In `DocbotConfig` (models.py):

| Field           | Default | Purpose                                 |
|-----------------|---------|------------------------------------------|
| use_agents      | False   | Enable agent exploration                 |
| agent_max_depth | 8       | Max recursion depth for delegation       |
| agent_model     | None    | Separate model for agents (optional)     |

## Extending

### Adding a new tool

1. Add the `@tool`-decorated function inside `create_tools()` in `tools.py`
2. Add it to the returned list
3. The graph will automatically pick it up (tools are bound to LLM)

### Changing agent behavior

Modify the system prompt in `prompts.py`. The prompt uses `{purpose}`
and `{context_packet}` template variables.

### Adding new event types

1. Emit from the relevant location (tool, store, or entry point)
2. Add the event type to the SSE endpoint in `server.py`
3. Handle in the frontend's `useAgentStream.ts` hook
