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

    is_mimo_flash = model_id == "xiaomi/mimo-v2-flash"

    llm = ChatOpenAI(
        model=model_id,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        # MIMO is more stable for tool-use loops at lower temperature.
        temperature=0.0 if is_mimo_flash else 0.1,
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

    def _mirror_event_snapshot(event: dict) -> None:
        """Best-effort mirror of live events into web snapshot state."""
        try:
            from ..web import server as web_server
            web_server._update_agent_state_snapshot(event)
        except Exception:
            # Snapshot mirroring is optional and must never impact exploration.
            pass

    async def _emit_event(event: dict) -> None:
        _mirror_event_snapshot(event)
        if event_queue:
            await event_queue.put(event)

    def _norm_target(value: str) -> str:
        return value.strip().replace("\\", "/").strip("/")

    def _scope_prefix(scope_root: str) -> str:
        norm = _norm_target(scope_root)
        return f"{norm}/" if norm else ""

    def _target_exists(target: str) -> bool:
        norm = _norm_target(target)
        if not norm:
            return False
        return any(p == norm or p.startswith(f"{norm}/") for p in scan_files)

    def _sample_scope_files(scope_files: list[str], limit: int = 6) -> list[str]:
        # Prefer shorter and more central files first.
        ranked = sorted(scope_files, key=lambda p: (p.count("/"), len(p), p))
        return ranked[:limit]

    async def _summarize_scope_mimo(
        *,
        scope_root: str,
        purpose_text: str,
        context_text: str,
        scope_files: list[str],
    ) -> str:
        sampled = _sample_scope_files(scope_files, limit=6)
        snippets: list[str] = []
        for rel in sampled[:4]:
            p = (repo_root / rel).resolve()
            try:
                p.relative_to(repo_root.resolve())
            except ValueError:
                continue
            if not p.is_file():
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            snippets.append(f"FILE: {rel}\n{txt[:1400]}")

        prompt = (
            "You are a repository analysis agent.\n"
            f"Scope root: {scope_root or '(repo root)'}\n"
            f"Purpose: {purpose_text}\n"
            f"Context: {context_text[:1500] or '(none)'}\n"
            f"Scope file count: {len(scope_files)}\n"
            f"Sample files: {json.dumps(sampled, indent=2)}\n\n"
            "Code snippets:\n"
            + ("\n\n---\n\n".join(snippets) if snippets else "(none)")
            + "\n\nReturn a concise technical summary (6-12 sentences) with concrete module/file references."
        )
        try:
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            content = getattr(resp, "content", "")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            summary = str(content).strip()
            return summary[:6000]
        except Exception as exc:
            logger.warning("MIMO summary fallback failed for scope '%s': %s", scope_root, exc)
            return f"Scope {scope_root or '(repo root)'} analyzed with {len(scope_files)} files."

    def _select_scope_files(target: str) -> list[str]:
        norm = target.strip().replace("\\", "/").strip("/")
        if not norm or norm == ".":
            return scan_files[:200]
        matches = [p for p in scan_files if p == norm or p.startswith(f"{norm}/")]
        return matches[:200] if matches else scan_files[:50]

    def _fallback_delegation_plans(
        *,
        scope_root: str,
        scope_files: list[str],
        summary: str,
        desired_count: int,
    ) -> list[dict[str, str]]:
        """Heuristic fallback when model planning fails to return valid JSON."""
        if desired_count <= 0:
            return []

        norm_scope = _norm_target(scope_root)
        scope_prefix = _scope_prefix(norm_scope)
        counts: dict[str, int] = {}
        for path in scope_files:
            clean = path.replace("\\", "/")
            if norm_scope:
                if not (clean == norm_scope or clean.startswith(scope_prefix)):
                    continue
                relative = clean[len(scope_prefix):] if clean.startswith(scope_prefix) else ""
            else:
                relative = clean
            parts = [p for p in relative.split("/") if p]
            if not parts:
                continue
            key = f"{norm_scope}/{parts[0]}" if norm_scope else parts[0]
            if key and not key.startswith(".") and key != norm_scope:
                counts[key] = counts.get(key, 0) + 1
        ranked = [k for k, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)]
        out: list[dict[str, str]] = []
        for target in ranked[:desired_count]:
            out.append(
                {
                    "target": target,
                    "name": f"delegate:{target}",
                    "purpose": f"Explore {target} in detail and summarize key architecture decisions.",
                    "context": (summary[:800] or f"Parent scope: {norm_scope or 'repo root'}"),
                }
            )
        return out

    async def _plan_delegations(
        *,
        depth: int,
        scope_root: str,
        scope_files: list[str],
        summary: str,
        desired_count: int,
    ) -> list[dict[str, str]]:
        """Ask the model to choose delegation targets/purposes from scope files."""
        if desired_count <= 0 or depth >= max_depth:
            return []

        norm_scope = _norm_target(scope_root)
        scope_prefix = _scope_prefix(norm_scope)

        # Build candidate directories from observed file structure.
        counts: dict[str, int] = {}
        for path in scope_files:
            clean = path.replace("\\", "/")
            if norm_scope:
                if not (clean == norm_scope or clean.startswith(scope_prefix)):
                    continue
                relative = clean[len(scope_prefix):] if clean.startswith(scope_prefix) else ""
            else:
                relative = clean
            parts = [p for p in relative.split("/") if p]
            if not parts:
                continue
            # Choose next-level directory inside current scope.
            key = f"{norm_scope}/{parts[0]}" if norm_scope else parts[0]
            if key and not key.startswith(".") and key != norm_scope:
                counts[key] = counts.get(key, 0) + 1
        candidates = [k for k, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:25]]
        if not candidates:
            return []

        prompt = (
            "You are planning child exploration delegations for a codebase analysis agent.\n"
            f"Current depth: {depth}. Max depth: {max_depth}.\n"
            f"Current scope root: {norm_scope or '(repo root)'}\n"
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
            if out:
                return out
            return _fallback_delegation_plans(
                scope_root=scope_root,
                scope_files=scope_files,
                summary=summary,
                desired_count=desired_count,
            )
        except Exception as exc:
            logger.warning("Delegation planning failed at depth %s: %s", depth, exc)
            return _fallback_delegation_plans(
                scope_root=scope_root,
                scope_files=scope_files,
                summary=summary,
                desired_count=desired_count,
            )

    async def _run_agent(
        *,
        agent_id: str,
        parent_id: str | None,
        agent_purpose: str,
        parent_context: str,
        depth: int,
        scope_root: str,
        ancestor_scopes: tuple[str, ...],
        scope_files: list[str],
    ) -> str:
        nonlocal child_seq
        await _emit_event(
            {
                "type": "agent_spawned",
                "agent_id": agent_id,
                "parent_id": parent_id,
                "purpose": agent_purpose,
                "depth": depth,
                "scope_root": scope_root,
            }
        )

        delegated_targets: set[str] = set()
        norm_scope = _norm_target(scope_root)
        scope_prefix = _scope_prefix(norm_scope)
        ancestor_norm = {_norm_target(s) for s in ancestor_scopes if _norm_target(s)}

        async def _delegate_child(target: str, name: str, child_purpose: str, child_context: str) -> str:
            nonlocal child_seq
            norm_target = _norm_target(target)
            if not norm_target:
                return "Delegation blocked: empty target."
            if norm_target in delegated_targets:
                return f"Delegation blocked: target '{norm_target}' already delegated by this agent."
            if norm_target == norm_scope:
                return f"Delegation blocked: target '{norm_target}' is this agent's own scope."
            if norm_target in ancestor_norm:
                return f"Delegation blocked: target '{norm_target}' is an ancestor scope."
            if norm_scope and not norm_target.startswith(scope_prefix):
                return (
                    f"Delegation blocked: target '{norm_target}' is outside scope "
                    f"'{norm_scope}'."
                )
            if not _target_exists(norm_target):
                return f"Delegation blocked: target '{norm_target}' has no matching source files."

            delegated_targets.add(norm_target)
            child_seq += 1
            delegate_counts[agent_id] = delegate_counts.get(agent_id, 0) + 1
            child_id = f"{agent_id}.{child_seq}"
            child_files = _select_scope_files(norm_target)
            return await _run_agent(
                agent_id=child_id,
                parent_id=agent_id,
                agent_purpose=child_purpose or f"Explore {norm_target}",
                parent_context=child_context,
                depth=depth + 1,
                scope_root=norm_target,
                ancestor_scopes=(*ancestor_scopes, norm_scope),
                scope_files=child_files,
            )

        def _desired_children_for_scope() -> int:
            if depth >= max_depth:
                return 0
            file_count = len(scope_files)
            if file_count < 15:
                return 0
            if depth == 0:
                if file_count >= 100:
                    return 3
                if file_count >= 40:
                    return 2
                return 1
            if depth == 1:
                if file_count >= 60:
                    return 3
                if file_count >= 25:
                    return 2
                return 1
            return 0

        if is_mimo_flash:
            summary = await _summarize_scope_mimo(
                scope_root=scope_root,
                purpose_text=agent_purpose,
                context_text=parent_context,
                scope_files=scope_files,
            )

            desired_children = _desired_children_for_scope()
            if desired_children > 0:
                plans = await _plan_delegations(
                    depth=depth,
                    scope_root=scope_root,
                    scope_files=scope_files,
                    summary=summary,
                    desired_count=desired_children,
                )
                for plan in plans:
                    await _delegate_child(
                        plan["target"],
                        plan["name"],
                        plan["purpose"],
                        plan["context"][:2000],
                    )

            await _emit_event(
                {"type": "agent_finished", "agent_id": agent_id, "summary": summary}
            )
            return summary

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

        recursion_limit = 50 if is_mimo_flash else 80

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
                if depth < max_depth and len(scope_files) >= 30:
                    initial_message += (
                        "\nDelegation policy: this is a broad scope. "
                        "Delegate at least two distinct child targets before finishing. "
                        "Do not delegate outside your current scope."
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
                    config={"callbacks": callbacks, "recursion_limit": recursion_limit},
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

            if is_mimo_flash:
                summary = await _summarize_scope_mimo(
                    scope_root=scope_root,
                    purpose_text=agent_purpose,
                    context_text=parent_context,
                    scope_files=scope_files,
                )
                await _emit_event(
                    {"type": "agent_finished", "agent_id": agent_id, "summary": summary}
                )
                return summary

            raise RuntimeError(
                f"Agent {agent_id} did not satisfy required actions "
                f"(summary policy) after retry."
            )
        except Exception as exc:
            if is_mimo_flash:
                logger.warning(
                    "Agent exploration graph path failed for %s (MIMO fallback): %s",
                    agent_id,
                    exc,
                )
                summary = await _summarize_scope_mimo(
                    scope_root=scope_root,
                    purpose_text=agent_purpose,
                    context_text=parent_context,
                    scope_files=scope_files,
                )
                await _emit_event(
                    {"type": "agent_finished", "agent_id": agent_id, "summary": summary}
                )
                return summary
            logger.error("Agent exploration failed for %s: %s", agent_id, exc)
            await _emit_event(
                {"type": "agent_error", "agent_id": agent_id, "error": str(exc)}
            )
            return ""

    root_summary = await _run_agent(
        agent_id=root_id,
        parent_id=None,
        agent_purpose=purpose,
        parent_context=context_packet,
        depth=0,
        scope_root="",
        ancestor_scopes=tuple(),
        scope_files=scan_files[:200],
    )

    # Model-driven delegation planning fallback:
    # if root did not delegate enough, ask the model to pick child scopes.
    if is_mimo_flash:
        return store

    large_repo = len(scan_files) >= 80
    # Shape-based delegation budget:
    # - top-level buckets and breadth under each bucket imply multiple child agents.
    # - for this repo shape (119 files, 33 dirs), target ~8-12 agents total.
    desired_root_children = 3 if large_repo else 1
    root_existing_children = delegate_counts.get(root_id, 0)
    if max_depth > 0 and root_existing_children < desired_root_children:
        plans = await _plan_delegations(
            depth=0,
            scope_root="",
            scope_files=scan_files[:200],
            summary=root_summary,
            desired_count=desired_root_children - root_existing_children,
        )
        for plan in plans:
            child_seq += 1
            child_id = f"{root_id}.model{child_seq}"
            child_target = _norm_target(plan["target"])
            child_scope_files = _select_scope_files(child_target)
            child_summary = await _run_agent(
                agent_id=child_id,
                parent_id=root_id,
                agent_purpose=plan["purpose"],
                parent_context=plan["context"][:2000],
                depth=1,
                scope_root=child_target,
                ancestor_scopes=("",),
                scope_files=child_scope_files,
            )

            # For large repos, also ask model to create at least one depth-2 child.
            if max_depth > 1 and large_repo:
                sub_plans = await _plan_delegations(
                    depth=1,
                    scope_root=child_target,
                    scope_files=child_scope_files,
                    summary=child_summary or root_summary,
                    desired_count=2,
                )
                for sub in sub_plans:
                    child_seq += 1
                    sub_target = _norm_target(sub["target"])
                    await _run_agent(
                        agent_id=f"{child_id}.model{child_seq}",
                        parent_id=child_id,
                        agent_purpose=sub["purpose"],
                        parent_context=sub["context"][:2000],
                        depth=2,
                        scope_root=sub_target,
                        ancestor_scopes=("", child_target),
                        scope_files=_select_scope_files(sub_target),
                    )

    return store


__all__ = ["run_agent_exploration"]
