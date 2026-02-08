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
    tools = create_tools(
        repo_root=repo_root,
        store=store,
        event_queue=event_queue,
    )

    graph = build_graph(llm, tools)

    # Build the root agent's initial state.
    from .prompts import build_system_prompt

    root_id = "root"
    purpose = "Explore the entire repository and document its architecture, patterns, and key design decisions."
    context_packet = ""

    # Gather file listing for context.
    scan_files = []
    if hasattr(scan_result, "source_files"):
        scan_files = [sf.path for sf in scan_result.source_files]

    system_prompt = build_system_prompt(purpose, context_packet)

    # Emit root agent spawned event.
    if event_queue:
        await event_queue.put({
            "type": "agent_spawned",
            "agent_id": root_id,
            "parent_id": None,
            "purpose": purpose,
            "depth": 0,
        })

    callbacks = [AgentEventCallback(event_queue, root_id)] if event_queue else []

    try:
        from langchain_core.messages import SystemMessage, HumanMessage

        initial_message = (
            f"You are exploring the repository at: {repo_root}\n"
            f"It contains {len(scan_files)} source files.\n"
            f"Top-level structure will be revealed when you use list_directory.\n"
            f"Max delegation depth: {max_depth}."
        )

        result = await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=initial_message),
                ],
                "agent_id": root_id,
                "parent_id": None,
                "purpose": purpose,
                "context_packet": context_packet,
                "repo_root": str(repo_root),
                "scope_files": scan_files[:50],
                "depth": 0,
                "max_depth": max_depth,
                "summary": "",
            },
            config={"callbacks": callbacks, "recursion_limit": 50},
        )

        if event_queue:
            await event_queue.put({
                "type": "agent_finished",
                "agent_id": root_id,
                "summary": result.get("summary", ""),
            })

    except Exception as exc:
        logger.error("Agent exploration failed: %s", exc)
        if event_queue:
            await event_queue.put({
                "type": "agent_error",
                "agent_id": root_id,
                "error": str(exc),
            })

    return store


__all__ = ["run_agent_exploration"]
