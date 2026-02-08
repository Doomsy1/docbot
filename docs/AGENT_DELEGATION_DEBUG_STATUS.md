# Agent Delegation Debug Status (Checkpoint)

Date: 2026-02-08
Branch: `New-Agent-Architecture`

## Summary
This checkpoint captures current state after migrating to LangGraph + live webapp and debugging the `run --viz` / exploration flow.

## What Works
- Root webapp route (`/`) now serves built frontend assets in all `--viz` code paths.
- `/api/pipeline` no longer 404s during live runs; it falls back to in-memory tracker events when no persisted events exist yet.
- SSE `/api/agent-stream` no longer returns 503 when no agents; it emits `done` with `{"no_agents": true}`.
- `/api/agent-state` now loads persisted `agent_state.json` when in-memory state is empty.
- Exploration hook no longer reconnect-spams due to stale closure.
- Retry cap/no-agents handling added in frontend exploration SSE logic.
- Browser auto-open added for viz entry points.
- `run` CLI currently defaults to agent mode (flag removed in this checkpoint).

## Current Problem (Core)
Agent delegation is still unreliable when driven purely by model tool-calling.
Observed behavior on `../fine-ill-do-it-myself`:
- Root agent consistently spawns and performs tool reads/listing.
- Root often returns a textual summary without issuing `delegate` tool calls.
- Result: no child `agent_spawned` events (`parent_id=root`) in affected runs.

## Evidence Collected
- Live/event traces show:
  - `agent_spawned(root)`
  - many `tool_start/list_directory` and `tool_start/read_file`
  - `agent_finished(root)` with empty or plain summary
  - zero `tool_start(delegate)` events in failing runs
- Strict prompt retries and tool-call policy prompts did not produce stable delegation.
- Forced policy around `finish` tool caused false failures because model frequently ends with plain assistant text instead of calling `finish`.

## Changes Attempted (and kept)
- Added recursive child-agent execution plumbing via async `delegate_fn` in tool factory.
- Added better callback stability (`on_chat_model_start` no-op; ignore empty tokens).
- Added backend integration tests for agent behavior and CLI defaults.
- Removed fragile hard requirement for `finish` tool call (summary text accepted).

## Changes Attempted (and reverted)
- Auto-spawn fallback child agents when no delegation happened (reverted on request).

## Open Risks
- Delegation depends on model compliance with tool-calling; currently nondeterministic.
- Integration test `test_run_async_agents_emits_child_delegation_events` still fails intermittently/consistently when root does not call `delegate`.

## Test Status in this checkpoint
- Passing:
  - `tests/test_exploration_graph.py` (including new callback/delegate-tool unit tests)
  - `tests/test_web_pipeline_api.py`
  - `tests/test_agent_integration_cli.py::test_run_help_no_agents_flag`
- Failing / unstable:
  - `tests/test_agent_integration_cli.py::test_run_async_agents_emits_child_delegation_events`

## Recommended Next Fix Direction
1. Move delegation selection to backend planner/orchestrator (deterministic child scope plan), not model discretion.
2. Keep model delegation as optional enhancement, not required for correctness.
3. Emit explicit delegation lifecycle events from backend so integration tests can validate deterministic child spawn count.
4. Keep frontend out of loop until backend deterministic delegation passes consistently.
