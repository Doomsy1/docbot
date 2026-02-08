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
import json
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

    def _select_scope_files(target: str) -> list[str]:
        norm = target.strip().replace("\\", "/").strip("/")
        if not norm or norm == ".":
            return scan_files[:200]
        matches = [p for p in scan_files if p == norm or p.startswith(f"{norm}/")]
        return matches[:200] if matches else scan_files[:50]

    async def _plan_delegations(
        *,
        depth: int,
        scope_files: list[str],
        summary: str,
        desired_count: int,
    ) -> list[dict[str, str]]:
        """Ask the model to choose delegation targets/purposes from scope files."""
        if desired_count <= 0 or depth >= max_depth:
            return []

        # Build candidate directories from observed file structure.
        counts: dict[str, int] = {}
        for path in scope_files:
            parts = path.replace("\\", "/").split("/")
            if len(parts) >= 2:
                key = "/".join(parts[:2])
            elif parts:
                key = parts[0]
            else:
                continue
            if key and not key.startswith("."):
                counts[key] = counts.get(key, 0) + 1
        candidates = [k for k, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:25]]
        if not candidates:
            return []

        prompt = (
            "You are planning child exploration delegations for a codebase analysis agent.\n"
            f"Current depth: {depth}. Max depth: {max_depth}.\n"
            f"Choose up to {desired_count} child delegations from the candidate targets below.\n"
            "Each item must include:\n"
            '- "target": exact candidate path\n'
            '- "name": short child label\n'
            '- "purpose": concise mission for child\n'
            '- "context": short context packet for child\n'
            "Return ONLY valid JSON array. No markdown fences.\n\n"
            f"Parent summary:\n{summary[:2000] or '(none)'}\n\n"
            f"Candidates:\n{json.dumps(candidates, indent=2)}"
        )
        try:
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            content = getattr(resp, "content", "")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            raw = str(content).strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                raw = raw.replace("json", "", 1).strip()
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                return []
            out: list[dict[str, str]] = []
            for item in parsed[:desired_count]:
                if not isinstance(item, dict):
                    continue
                target = str(item.get("target", "")).strip()
                if not target or target not in candidates:
                    continue
                out.append(
                    {
                        "target": target,
                        "name": str(item.get("name", f"delegate:{target}")).strip() or f"delegate:{target}",
                        "purpose": str(item.get("purpose", f"Explore {target}")).strip() or f"Explore {target}",
                        "context": str(item.get("context", summary[:500])).strip(),
                    }
                )
            return out
        except Exception as exc:
            logger.warning("Delegation planning failed at depth %s: %s", depth, exc)
            return []

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

    # Model-driven delegation planning fallback:
    # if root did not delegate enough, ask the model to pick child scopes.
    large_repo = len(scan_files) >= 80
    desired_root_children = 2 if large_repo else 1
    root_existing_children = delegate_counts.get(root_id, 0)
    if max_depth > 0 and root_existing_children < desired_root_children:
        plans = await _plan_delegations(
            depth=0,
            scope_files=scan_files[:200],
            summary=root_summary,
            desired_count=desired_root_children - root_existing_children,
        )
        for plan in plans:
            child_seq += 1
            child_id = f"{root_id}.model{child_seq}"
            child_scope_files = _select_scope_files(plan["target"])
            child_summary = await _run_agent(
                agent_id=child_id,
                parent_id=root_id,
                agent_purpose=plan["purpose"],
                parent_context=plan["context"][:2000],
                depth=1,
                scope_files=child_scope_files,
            )

            # For large repos, also ask model to create at least one depth-2 child.
            if max_depth > 1 and large_repo:
                sub_plans = await _plan_delegations(
                    depth=1,
                    scope_files=child_scope_files,
                    summary=child_summary or root_summary,
                    desired_count=1,
                )
                for sub in sub_plans:
                    child_seq += 1
                    await _run_agent(
                        agent_id=f"{child_id}.model{child_seq}",
                        parent_id=child_id,
                        agent_purpose=sub["purpose"],
                        parent_context=sub["context"][:2000],
                        depth=2,
                        scope_files=_select_scope_files(sub["target"]),
                    )

    return store


__all__ = ["run_agent_exploration"]
