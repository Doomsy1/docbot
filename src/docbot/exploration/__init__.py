"""Exploration module -- LangGraph-based recursive agent exploration.

This module replaces the older ``docbot.agents`` system with a single
generalized recursive agent built on LangGraph.  Key improvements:

- Single agent type that adapts its behavior based on purpose/context
- Shared notepad via LangGraph InMemoryStore for cross-branch knowledge
- Built-in LLM tool calling (no regex parsing)
- Async event streaming via callback queue for live visualization
- Runs in parallel with standard extraction (not sequential)

Entry point:
    ``run_agent_exploration()`` -- call from the orchestrator after scan.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import DocbotConfig
    from .store import NotepadStore

logger = logging.getLogger(__name__)


async def run_agent_exploration(
    repo_root: Path,
    scan_result: object,
    config: "DocbotConfig",
    event_queue: asyncio.Queue | None = None,
) -> "NotepadStore":
    """Run LangGraph-based agent exploration on the repository.

    This is the main entry point called by the orchestrator.  It:

    1. Creates a ``ChatOpenAI`` client configured for OpenRouter
    2. Builds the LangGraph agent graph
    3. Runs the root agent, which delegates to child agents as needed
    4. Returns a populated ``NotepadStore`` with all agent findings

    Parameters
    ----------
    repo_root:
        Absolute path to the repository being documented.
    scan_result:
        The ``ScanResult`` from the scanner stage.
    config:
        Docbot configuration (agent_max_depth, agent_model, etc.).
    event_queue:
        Optional async queue for pushing live visualization events.
        When ``None``, no events are emitted.

    Returns
    -------
    NotepadStore
        The populated shared notepad containing all agent discoveries.
    """
    from .graph import build_graph
    from .store import NotepadStore
    from .callbacks import AgentEventCallback
    from langchain_core.messages import HumanMessage, SystemMessage

    store = NotepadStore(event_queue=event_queue)

    # Determine model -- use agent_model if set, otherwise main model.
    model_id = config.agent_model or config.model
    max_depth = config.agent_max_depth

    # Build the LLM client for agents.
    import os
    api_key = os.environ.get("OPENROUTER_KEY", "")
    if not api_key:
        logger.warning("OPENROUTER_KEY not set; agent exploration skipped")
        return store

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=model_id,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        temperature=0.1,
        streaming=True,
    )

    # Collect top-level files/dirs for root agent context.
    from .tools import create_tools

    # Build the root agent's initial state.
    from .prompts import build_system_prompt

    root_id = "root"
    purpose = "Explore the entire repository and document its architecture, patterns, and key design decisions."
    context_packet = ""

    # Gather file listing for context.
    scan_files = []
    if hasattr(scan_result, "source_files"):
        scan_files = [sf.path for sf in scan_result.source_files]

    child_seq = 0
    delegate_counts: dict[str, int] = {}
    large_repo = len(scan_files) >= 80

    def _select_scope_files(target: str) -> list[str]:
        norm = target.strip().replace("\\", "/").strip("/")
        if not norm or norm == ".":
            return scan_files[:200]
        matches = [p for p in scan_files if p == norm or p.startswith(f"{norm}/")]
        return matches[:200] if matches else scan_files[:50]

    async def _run_agent(
        *,
        agent_id: str,
        parent_id: str | None,
        agent_purpose: str,
        parent_context: str,
        depth: int,
        scope_files: list[str],
    ) -> str:
        nonlocal child_seq
        if event_queue:
            await event_queue.put(
                {
                    "type": "agent_spawned",
                    "agent_id": agent_id,
                    "parent_id": parent_id,
                    "purpose": agent_purpose,
                    "depth": depth,
                }
            )

        async def _delegate_child(target: str, name: str, child_purpose: str, child_context: str) -> str:
            nonlocal child_seq
            child_seq += 1
            delegate_counts[agent_id] = delegate_counts.get(agent_id, 0) + 1
            child_id = f"{agent_id}.{child_seq}"
            child_files = _select_scope_files(target)
            return await _run_agent(
                agent_id=child_id,
                parent_id=agent_id,
                agent_purpose=child_purpose or f"Explore {target}",
                parent_context=child_context,
                depth=depth + 1,
                scope_files=child_files,
            )

        tools = create_tools(
            repo_root=repo_root,
            store=store,
            event_queue=event_queue,
            agent_id=agent_id,
            delegate_fn=_delegate_child,
            current_depth=depth,
            max_depth=max_depth,
        )
        callbacks = [AgentEventCallback(event_queue, agent_id)] if event_queue else []

        def _extract_finish_summary(messages: list) -> str:
            finish_ids: set[str] = set()
            for msg in messages:
                calls = getattr(msg, "tool_calls", None) or []
                for call in calls:
                    if call.get("name") == "finish" and call.get("id"):
                        finish_ids.add(call["id"])
            if finish_ids:
                for msg in reversed(messages):
                    tool_call_id = getattr(msg, "tool_call_id", None)
                    if tool_call_id in finish_ids:
                        content = getattr(msg, "content", "")
                        return content if isinstance(content, str) else str(content)
            for msg in reversed(messages):
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()
            return ""

        retry_directive = (
            "You exited without a usable final summary. Retry now and provide "
            "a concise final summary in your final response."
        )

        try:
            for attempt in range(2):
                graph = build_graph(
                    llm,
                    tools,
                    tool_choice=None,
                )
                initial_message = (
                    f"You are exploring repository path: {repo_root}\n"
                    f"Assigned scope file count: {len(scope_files)}.\n"
                    f"Max delegation depth: {max_depth}. Current depth: {depth}."
                )
                if parent_id is None and depth < max_depth:
                    top_targets = sorted(
                        {
                            p.split("/", 1)[0]
                            for p in scope_files
                            if "/" in p and not p.startswith(".")
                        }
                    )[:8]
                    if top_targets:
                        initial_message += (
                            "\nCandidate child targets: "
                            + ", ".join(top_targets)
                            + ". Delegate only when it improves coverage."
                        )
                if attempt > 0:
                    initial_message = f"{initial_message}\n\n{retry_directive}"
                result = await graph.ainvoke(
                    {
                        "messages": [
                            SystemMessage(content=build_system_prompt(agent_purpose, parent_context)),
                            HumanMessage(content=initial_message),
                        ],
                        "agent_id": agent_id,
                        "parent_id": parent_id,
                        "purpose": agent_purpose,
                        "context_packet": parent_context,
                        "repo_root": str(repo_root),
                        "scope_files": scope_files,
                        "depth": depth,
                        "max_depth": max_depth,
                        "summary": "",
                    },
                    config={"callbacks": callbacks, "recursion_limit": 80},
                )
                messages = result.get("messages", [])
                summary = _extract_finish_summary(messages).strip()
                if summary:
                    if event_queue:
                        await event_queue.put(
                            {"type": "agent_finished", "agent_id": agent_id, "summary": summary}
                        )
                    return summary
                logger.warning(
                    "Agent %s ended without usable summary (attempt=%s)",
                    agent_id, attempt + 1,
                )

            raise RuntimeError(
                f"Agent {agent_id} did not satisfy required actions "
                f"(summary policy) after retry."
            )
        except Exception as exc:
            logger.error("Agent exploration failed for %s: %s", agent_id, exc)
            if event_queue:
                await event_queue.put(
                    {"type": "agent_error", "agent_id": agent_id, "error": str(exc)}
                )
            return ""

    root_summary = await _run_agent(
        agent_id=root_id,
        parent_id=None,
        agent_purpose=purpose,
        parent_context=context_packet,
        depth=0,
        scope_files=scan_files[:200],
    )

    # Deterministic delegation plan: always run focused child agents over the
    # largest top-level code regions so exploration remains reliable even when
    # model tool-calling is inconsistent.
    if max_depth > 0:
        top_counts: dict[str, int] = {}
        for path in scan_files:
            parts = path.split("/", 1)
            if not parts:
                continue
            top = parts[0]
            if top.startswith("."):
                continue
            top_counts[top] = top_counts.get(top, 0) + 1
        planned = [name for name, _ in sorted(top_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]]
        for idx, target in enumerate(planned, start=1):
            child_id = f"{root_id}.plan{idx}"
            child_scope_files = _select_scope_files(target)
            child_summary = await _run_agent(
                agent_id=child_id,
                parent_id=root_id,
                agent_purpose=f"Deep-dive '{target}' and record architecture, data flow, and key implementation details.",
                parent_context=(root_summary or "")[:2000],
                depth=1,
                scope_files=child_scope_files,
            )

            # For large repositories, enforce a second delegation layer.
            if max_depth > 1 and large_repo:
                sub_counts: dict[str, int] = {}
                for path in child_scope_files:
                    parts = path.replace("\\", "/").split("/")
                    if len(parts) >= 2 and parts[0] == target:
                        sub = parts[1]
                        if sub and not sub.startswith("."):
                            sub_counts[sub] = sub_counts.get(sub, 0) + 1
                sub_targets = [n for n, _ in sorted(sub_counts.items(), key=lambda kv: kv[1], reverse=True)[:2]]
                if not sub_targets and child_scope_files:
                    # Fallback to at least one depth-2 agent even if child files
                    # are flat under the top-level directory.
                    sub_targets = [child_scope_files[0].replace("\\", "/")]

                for sub_idx, sub in enumerate(sub_targets, start=1):
                    sub_path = sub if "/" in sub else f"{target}/{sub}"
                    await _run_agent(
                        agent_id=f"{child_id}.plan{sub_idx}",
                        parent_id=child_id,
                        agent_purpose=(
                            f"Deep-dive '{sub_path}' and capture implementation details, "
                            f"critical data flow, and notable concerns."
                        ),
                        parent_context=(child_summary or root_summary or "")[:2000],
                        depth=2,
                        scope_files=_select_scope_files(sub_path),
                    )

    return store


__all__ = ["run_agent_exploration"]
