"""Integration checks for bounded agent exploration on a real repository.

These tests run only when both OPENROUTER_KEY and the local integration repo
are available. They validate agent behavior without requiring the web frontend.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from docbot.cli import _load_dotenv
from docbot.exploration import run_agent_exploration
from docbot.models import DocbotConfig
from docbot.pipeline.scanner import scan_repo


def _integration_repo() -> Path:
    return (Path(__file__).resolve().parents[1] / "../fine-ill-do-it-myself").resolve()


def _has_openrouter_key() -> bool:
    return bool(os.environ.get("OPENROUTER_KEY", "").strip())


@pytest.mark.skipif(not _integration_repo().exists(), reason="integration repo not found")
def test_mimo_exploration_spawns_multi_level_agents_without_errors() -> None:
    _load_dotenv(Path.cwd())
    if not _has_openrouter_key():
        pytest.skip("OPENROUTER_KEY not configured")

    repo = _integration_repo()
    scan = scan_repo(repo)
    queue: asyncio.Queue = asyncio.Queue(maxsize=20000)
    cfg = DocbotConfig(
        model="xiaomi/mimo-v2-flash",
        agent_model="xiaomi/mimo-v2-flash",
        use_agents=True,
        agent_depth=2,
    )

    asyncio.run(
        run_agent_exploration(
            repo_root=repo,
            scan_result=scan,
            config=cfg,
            event_queue=queue,
        )
    )

    events: list[dict] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    spawned = [e for e in events if e.get("type") == "agent_spawned"]
    errors = [e for e in events if e.get("type") == "agent_error"]
    finished = [e for e in events if e.get("type") == "agent_finished"]

    assert len(spawned) >= 5, "expected broad exploration with multiple delegated agents"
    assert any(e.get("parent_id") == "root" for e in spawned), "expected root delegations"
    assert any((e.get("depth") or 0) >= 2 for e in spawned), "expected depth-2 delegates"
    assert not errors, "expected no runtime agent_error events"
    assert len(finished) == len(spawned), "every spawned agent should finish"


@pytest.mark.skipif(not _integration_repo().exists(), reason="integration repo not found")
def test_mimo_child_scopes_stay_within_parent_scope() -> None:
    _load_dotenv(Path.cwd())
    if not _has_openrouter_key():
        pytest.skip("OPENROUTER_KEY not configured")

    repo = _integration_repo()
    scan = scan_repo(repo)
    queue: asyncio.Queue = asyncio.Queue(maxsize=20000)
    cfg = DocbotConfig(
        model="xiaomi/mimo-v2-flash",
        agent_model="xiaomi/mimo-v2-flash",
        use_agents=True,
        agent_depth=2,
    )

    asyncio.run(
        run_agent_exploration(
            repo_root=repo,
            scan_result=scan,
            config=cfg,
            event_queue=queue,
        )
    )

    events: list[dict] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    spawned = [e for e in events if e.get("type") == "agent_spawned"]
    scopes = {e.get("agent_id", ""): str(e.get("scope_root", "")).strip("/") for e in spawned}
    parents = {e.get("agent_id", ""): e.get("parent_id") for e in spawned}

    for agent_id, parent_id in parents.items():
        if not parent_id or parent_id not in scopes:
            continue
        parent_scope = scopes[parent_id]
        child_scope = scopes.get(agent_id, "")
        if not parent_scope:
            # Root parent can delegate to any repo-internal top-level scope.
            assert child_scope
            continue
        assert child_scope != parent_scope
        assert child_scope.startswith(f"{parent_scope}/"), (
            f"child scope '{child_scope}' must stay within parent scope '{parent_scope}'"
        )
