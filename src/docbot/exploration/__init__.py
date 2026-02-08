"""Backboard-native recursive exploration agents.

This module runs a bounded recursive exploration pass in parallel with the
standard extractor pipeline. Agents emit live events for the UI and write
findings into the shared NotepadStore.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..llm import LLMClient

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
    """Run recursive agent exploration using Backboard LLM calls."""
    from .store import NotepadStore

    store = NotepadStore(event_queue=event_queue)
    api_key = os.environ.get("BACKBOARD_API_KEY", "").strip()
    if not api_key:
        logger.warning("BACKBOARD_API_KEY not set; agent exploration skipped")
        return store

    model_id = config.agent_model or config.model
    max_depth = max(0, int(config.agent_max_depth))
    llm = LLMClient(
        api_key=api_key,
        model=model_id,
        max_concurrency=max(1, int(config.agent_scope_max_parallel)),
        backoff_enabled=config.llm_backoff_enabled,
        max_retries=config.llm_backoff_max_retries,
        adaptive_reduction_factor=config.llm_adaptive_reduction_factor,
    )

    scan_files: list[str] = []
    if hasattr(scan_result, "source_files"):
        scan_files = [sf.path for sf in scan_result.source_files]

    def _normalize(value: str) -> str:
        return value.strip().replace("\\", "/").strip("/")

    def _scope_prefix(scope_root: str) -> str:
        return f"{scope_root}/" if scope_root else ""

    def _target_exists(target: str) -> bool:
        norm = _normalize(target)
        if not norm:
            return False
        return any(p == norm or p.startswith(f"{norm}/") for p in scan_files)

    def _select_scope_files(target: str) -> list[str]:
        norm = _normalize(target)
        if not norm:
            return scan_files[:220]
        matches = [p for p in scan_files if p == norm or p.startswith(f"{norm}/")]
        return matches[:220] if matches else []

    def _sample_scope_files(scope_files: list[str], limit: int = 8) -> list[str]:
        ranked = sorted(scope_files, key=lambda p: (p.count("/"), len(p), p))
        return ranked[:limit]

    def _candidate_targets(scope_root: str, scope_files: list[str]) -> list[str]:
        norm_scope = _normalize(scope_root)
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
            if key and key != norm_scope and not key.startswith("."):
                counts[key] = counts.get(key, 0) + 1
        return [k for k, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:30]]

    def _desired_children_for_scope(depth: int, file_count: int) -> int:
        if depth >= max_depth or file_count < 12:
            return 0
        if depth == 0:
            if file_count >= 100:
                return 4
            if file_count >= 45:
                return 3
            return 2
        if depth == 1:
            if file_count >= 60:
                return 3
            if file_count >= 24:
                return 2
            return 1
        if depth == 2 and file_count >= 30:
            return 1
        return 0

    def _mirror_event_snapshot(event: dict) -> None:
        try:
            from ..web import server as web_server
            web_server._update_agent_state_snapshot(event)
        except Exception:
            pass

    async def _emit_event(event: dict) -> None:
        _mirror_event_snapshot(event)
        if event_queue is not None:
            await event_queue.put(event)

    def _extract_json_array(raw: str) -> list[dict]:
        txt = raw.strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            txt = txt.replace("json", "", 1).strip()
        try:
            data = json.loads(txt)
            return data if isinstance(data, list) else []
        except Exception:
            start = txt.find("[")
            end = txt.rfind("]")
            if start >= 0 and end > start:
                try:
                    data = json.loads(txt[start : end + 1])
                    return data if isinstance(data, list) else []
                except Exception:
                    return []
            return []

    async def _summarize_scope(
        *,
        scope_root: str,
        purpose_text: str,
        context_text: str,
        scope_files: list[str],
    ) -> str:
        sampled = _sample_scope_files(scope_files, limit=8)
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
            snippets.append(f"FILE: {rel}\n{txt[:1600]}")

        prompt = (
            "Summarize this code scope for architecture learning.\n"
            f"Scope root: {scope_root or '(repo root)'}\n"
            f"Purpose: {purpose_text}\n"
            f"Parent context: {context_text[:1500] or '(none)'}\n"
            f"Scope file count: {len(scope_files)}\n"
            f"Sample files: {json.dumps(sampled, indent=2)}\n\n"
            "Write concise markdown with sections:\n"
            "## What It Is\n## Key Flow\n## Important Files\n"
            "Keep it concrete with file references.\n\n"
            "Code snippets:\n"
            + ("\n\n---\n\n".join(snippets) if snippets else "(none)")
        )
        try:
            summary = await llm.ask(
                prompt,
                system="You are a pragmatic staff engineer explaining a codebase. Be specific and concise.",
            )
            return (summary or "").strip()[:7000]
        except Exception as exc:
            logger.warning("Agent summary failed for scope '%s': %s", scope_root, exc)
            return f"Scope {scope_root or '(repo root)'} analyzed with {len(scope_files)} files."

    async def _plan_delegations(
        *,
        depth: int,
        scope_root: str,
        scope_files: list[str],
        summary: str,
        desired_count: int,
    ) -> list[dict[str, str]]:
        if desired_count <= 0 or depth >= max_depth:
            return []

        candidates = _candidate_targets(scope_root, scope_files)
        if not candidates:
            return []

        norm_scope = _normalize(scope_root)
        prompt = (
            "You are planning child exploration delegations for a codebase analysis agent.\n"
            f"Current depth: {depth}. Max depth: {max_depth}.\n"
            f"Current scope root: {norm_scope or '(repo root)'}\n"
            f"Target delegation count: {desired_count}.\n"
            "Default behavior: return exactly target count unless a strong reason prevents it.\n"
            "Under-delegation requires a concrete reason tied to scope shape (tiny scope, cohesive module, depth cap).\n"
            "Avoid vague reasons like 'good enough'.\n"
            f"Choose child delegations from the candidate targets below.\n"
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
            raw = await llm.ask(
                prompt,
                system="Return strict JSON only. No markdown.",
                json_mode=True,
            )
            parsed = _extract_json_array(raw)
        except Exception as exc:
            logger.warning("Delegation planning failed at depth %s: %s", depth, exc)
            parsed = []

        out: list[dict[str, str]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target", "")).strip()
            if not target or target not in candidates:
                continue
            out.append(
                {
                    "target": target,
                    "name": str(item.get("name", f"delegate:{target}")).strip() or f"delegate:{target}",
                    "purpose": str(item.get("purpose", f"Explore {target} in detail.")).strip(),
                    "context": str(item.get("context", summary[:700])).strip(),
                }
            )
            if len(out) >= desired_count:
                break

        if out:
            return out

        # Heuristic fallback when planning JSON is invalid.
        return [
            {
                "target": t,
                "name": f"delegate:{t}",
                "purpose": f"Explore {t} and summarize architecture and responsibilities.",
                "context": summary[:700],
            }
            for t in candidates[:desired_count]
        ]

    agent_limit = 48
    agent_count = 0

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
        nonlocal agent_count
        if agent_count >= agent_limit:
            return "Agent budget reached; skipped."
        agent_count += 1

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

        try:
            summary = await _summarize_scope(
                scope_root=scope_root,
                purpose_text=agent_purpose,
                context_text=parent_context,
                scope_files=scope_files,
            )
            topic_scope = _normalize(scope_root) or "repo"
            store.write(
                topic=f"scope.{topic_scope}",
                content=summary[:2200],
                author=agent_id,
            )

            await _emit_event(
                {"type": "agent_finished", "agent_id": agent_id, "summary": summary}
            )

            desired = _desired_children_for_scope(depth, len(scope_files))
            if desired <= 0:
                return summary

            plans = await _plan_delegations(
                depth=depth,
                scope_root=scope_root,
                scope_files=scope_files,
                summary=summary,
                desired_count=desired,
            )

            delegated_targets: set[str] = set()
            norm_scope = _normalize(scope_root)
            prefix = _scope_prefix(norm_scope)
            ancestors = {_normalize(s) for s in ancestor_scopes if _normalize(s)}

            child_idx = 0
            for plan in plans:
                target = _normalize(plan["target"])
                if not target or target in delegated_targets:
                    continue
                if target == norm_scope or target in ancestors:
                    continue
                if norm_scope and not target.startswith(prefix):
                    continue
                if not _target_exists(target):
                    continue

                delegated_targets.add(target)
                child_idx += 1
                child_files = _select_scope_files(target)
                await _run_agent(
                    agent_id=f"{agent_id}.{child_idx}",
                    parent_id=agent_id,
                    agent_purpose=plan["purpose"] or f"Explore {target}",
                    parent_context=plan["context"][:2000],
                    depth=depth + 1,
                    scope_root=target,
                    ancestor_scopes=(*ancestor_scopes, norm_scope),
                    scope_files=child_files,
                )

            return summary
        except Exception as exc:
            logger.error("Agent exploration failed for %s: %s", agent_id, exc)
            await _emit_event(
                {"type": "agent_error", "agent_id": agent_id, "error": str(exc)}
            )
            return ""

    await _run_agent(
        agent_id="root",
        parent_id=None,
        agent_purpose=(
            "Explore the repository architecture and delegate deeper analysis to major "
            "subsystems so the final documentation captures real structure and flow."
        ),
        parent_context="",
        depth=0,
        scope_root="",
        ancestor_scopes=tuple(),
        scope_files=scan_files[:220],
    )

    return store


__all__ = ["run_agent_exploration"]
