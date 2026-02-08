"""CLI + pipeline integration tests for agent exploration.

These tests intentionally avoid frontend dependencies. They validate that
agent exploration runs through CLI/pipeline paths and that delegation emits
child agents in the event stream.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docbot.cli import app
from docbot.cli import _load_dotenv
from docbot.llm import LLMClient
from docbot.pipeline.orchestrator import run_async
from docbot.pipeline.tracker import PipelineTracker


def _integration_repo() -> Path:
    # Requested local integration target from user workflow.
    return (Path(__file__).resolve().parents[1] / "../fine-ill-do-it-myself").resolve()


def _has_openrouter_key() -> bool:
    return bool(os.environ.get("OPENROUTER_KEY", "").strip())


@pytest.mark.skipif(not _integration_repo().exists(), reason="integration repo not found")
def test_run_async_agents_emits_child_delegation_events(tmp_path: Path) -> None:
    _load_dotenv(Path.cwd())
    if not _has_openrouter_key():
        pytest.skip("OPENROUTER_KEY not configured")
    repo = _integration_repo()
    queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
    tracker = PipelineTracker()
    llm = LLMClient(api_key=os.environ["OPENROUTER_KEY"], model="openai/gpt-oss-20b")

    run_dir = asyncio.run(
        run_async(
            repo_path=repo,
            output_base=tmp_path,
            max_scopes=3,
            concurrency=2,
            timeout=120.0,
            llm_client=llm,
            tracker=tracker,
            use_agents=True,
            agent_depth=2,
            event_queue=queue,
        )
    )

    events: list[dict] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    spawned = [e for e in events if e.get("type") == "agent_spawned"]
    assert spawned, "expected at least root spawn event"
    # Delegation must produce at least one child.
    assert any(e.get("parent_id") == "root" for e in spawned), (
        "expected delegated child agent spawned from root"
    )

    assert not any(e.get("type") == "agent_error" for e in events), (
        "agent exploration should complete without runtime errors"
    )
    # If notes were written, they should be persisted.
    notepads_path = run_dir / "notepads" / "all_topics.json"
    if notepads_path.exists():
        data = json.loads(notepads_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)


def test_run_help_no_agents_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--agents" not in result.stdout
