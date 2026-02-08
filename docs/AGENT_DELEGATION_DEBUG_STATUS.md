# Agent Delegation Debug Status

Date: 2026-02-08  
Branch: `New-Agent-Architecture`

## Purpose
This document captures what was changed to stabilize and tune agent delegation after the LangGraph migration, with emphasis on `xiaomi/mimo-v2-flash` behavior.

## Commands Used for Validation
- `docbot run ../fine-ill-do-it-myself --output docbot_data --viz`
- `py -m pytest -q tests/test_agent_integration_cli.py -s`
- `py -m pytest -q tests/test_agent_exploration_integration.py -s`
- `py -m pytest -q tests/test_web_pipeline_api.py tests/test_renderer_llm_event_loop.py`
- `py -m pytest -q tests/test_exploration_prompts.py`

## Baseline Problems (Before Fixes)
1. MIMO tool-loop recursion failures (`GRAPH_RECURSION_LIMIT`) caused unstable delegation.
2. Exploration state was often empty after run completion unless SSE had been actively consumed.
3. Renderer could fail with `Semaphore ... is bound to a different event loop`.
4. Delegation was too conservative for deep search, often producing ~5-7 agents on the integration repo.

## Implemented Fixes

### 1) Stabilized MIMO execution path and sandboxed delegation
Commits:
- `db01a23` Stabilize MIMO delegation flow and live agent state persistence
- `5a61069` Tune MIMO delegation breadth/depth for deeper dynamic exploration

Key changes:
- Added bounded MIMO-first exploration path with model-driven planning + recursive delegation.
- Enforced delegation sandbox constraints:
  - no self-target
  - no ancestor-target
  - no out-of-scope target
  - no duplicate sibling target
  - must map to real scanned source files
- Added fallback planner top-up when model under-delegates relative to desired count.

### 2) Observability + persisted state
Commits:
- `dda7577` Persist scope_root in agent snapshot for exploration observability
- `db01a23` Stabilize MIMO delegation flow and live agent state persistence

Key changes:
- `agent_spawned` snapshot now stores `scope_root`.
- Live event queue setup resets stale snapshot state at run start.
- Agent/notepad events are mirrored into server snapshot even when no SSE client is connected.
- `agent_state.json` persistence remains active for completed live runs.

### 3) Prompt policy hardening
Commit:
- `ffe8772` Strengthen delegation prompt policy and under-delegation rationale

Key changes:
- System prompt now explicitly says under-delegation must have strong concrete reasons.
- Added good vs weak reason examples in prompt text.
- Delegation planner prompt uses a target count framing with explicit under-delegation rationale requirement.

### 4) Renderer event-loop reliability
Commit:
- `db01a23` Stabilize MIMO delegation flow and live agent state persistence

Key changes:
- `render_with_llm()` now keeps LLM generation on one event loop (no nested `asyncio.run` in executor threads).
- Eliminated observed semaphore cross-loop failures in validated runs.

## Current Behavior (Integration Repo)
Repository view used by scanner:
- `119` source files
- main top-level buckets: `racing_sim` and `legacy`

Observed agent counts:
- Earlier baseline: ~`5-7`
- After tuning: depth-4 default path typically `10+` in direct exploration runs
  - calibration run showed `10` at depth 4
  - an unconstrained sample showed `17` before final breadth calibration

Current defaults:
- `agent_depth` default is now `4` (run/orchestrator/config path).
- `docbot run` still prints `max_depth=<value>` from orchestrator; this should match passed depth.

## Tests Added/Updated
- `tests/test_agent_exploration_integration.py`
  - multi-level spawn + no-error assertions
  - sandbox scope containment assertions
  - deep-search test expecting double-digit agent count at depth 4
- `tests/test_renderer_llm_event_loop.py`
  - regression test for renderer LLM event-loop consistency
- `tests/test_web_pipeline_api.py`
  - scope_root snapshot persistence
  - snapshot reset semantics
  - notepad snapshot mirroring without SSE consumer
- `tests/test_exploration_prompts.py`
  - verifies prompt includes under-delegation policy and examples

## Open Considerations
1. Prompt-only delegation policy changes improve guidance but did not materially increase counts by themselves; count uplift came from planner/budget logic.
2. There is still variance run-to-run due to model choices; tests assert minimum behavior, not exact tree shape.
3. If desired target is specifically "usually 10-12", further tuning should focus on depth-3/4 child caps and file-count thresholds in `_desired_children_for_scope()`.

## Quick Handoff for Future Agents
1. Start with `tests/test_agent_exploration_integration.py`.
2. Then run `docbot run ../fine-ill-do-it-myself --output docbot_data --viz`.
3. Verify:
   - `/api/agent-state` is non-empty after run (even without active SSE consumer),
   - no renderer semaphore loop errors,
   - depth reaches expected level for configured `agent_depth`.
