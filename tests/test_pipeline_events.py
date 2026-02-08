"""Tests for pipeline event recording and persistence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from docbot.models import DocbotConfig, DocsIndex, ScopePlan, ScopeResult
from docbot.pipeline import orchestrator
from docbot.pipeline.tracker import AgentState, PipelineTracker


def test_tracker_records_agent_llm_and_tool_events() -> None:
    tracker = PipelineTracker()
    tracker.set_run_id("run-123")

    tracker.add_node("scope.auth", "Auth Scope", agent_type="scope")
    tracker.set_state("scope.auth", AgentState.running, "starting")
    tracker.append_text("scope.auth", "Reading auth.py")
    tracker.record_tool_call(
        "scope.auth",
        "read_file",
        {"path": "src/auth.py"},
        "=== src/auth.py ===",
    )
    tracker.set_state("scope.auth", AgentState.done, "done")

    snapshot = tracker.snapshot()
    node = snapshot["nodes"][0]
    assert node["agent_type"] == "scope"
    assert "Reading auth.py" in node["llm_text"]
    assert node["tool_calls"][0]["name"] == "read_file"

    exported = tracker.export_events()
    event_types = [e["type"] for e in exported["events"]]
    assert exported["run_id"] == "run-123"
    assert "text" in event_types
    assert "tool_call" in event_types


def test_generate_async_saves_pipeline_event_log(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    docbot_root = repo_root / ".docbot"
    docbot_root.mkdir()

    plan = ScopePlan(scope_id="scope.auth", title="Auth", paths=["src/auth.py"])
    scope_result = ScopeResult(
        scope_id="scope.auth",
        title="Auth",
        paths=["src/auth.py"],
        summary="Auth scope summary",
        languages=["python"],
    )
    docs_index = DocsIndex(
        repo_path=str(repo_root),
        generated_at="2026-02-07T00:00:00Z",
        scopes=[scope_result],
        languages=["python"],
    )

    async def _fake_scan(*_args, **_kwargs):
        return SimpleNamespace(source_files=[SimpleNamespace(path="src/auth.py")], languages=["python"], packages=[], entrypoints=[])

    async def _fake_plan(*_args, **_kwargs):
        return [plan]

    async def _fake_explore(*_args, **_kwargs):
        return [scope_result]

    async def _fake_reduce(*_args, **_kwargs):
        return docs_index

    async def _fake_render(*_args, **_kwargs):
        return []

    monkeypatch.setattr(orchestrator, "_run_scan", _fake_scan)
    monkeypatch.setattr(orchestrator, "_run_plan", _fake_plan)
    monkeypatch.setattr(orchestrator, "_run_explore", _fake_explore)
    monkeypatch.setattr(orchestrator, "_run_reduce", _fake_reduce)
    monkeypatch.setattr(orchestrator, "_run_render", _fake_render)

    tracker = PipelineTracker()
    asyncio.run(
        orchestrator.generate_async(
            docbot_root=docbot_root,
            config=DocbotConfig(max_scopes=1),
            llm_client=None,
            tracker=tracker,
        )
    )

    state = json.loads((docbot_root / "state.json").read_text(encoding="utf-8"))
    run_id = state["last_run_id"]
    events_path = docbot_root / "history" / run_id / "pipeline_events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))

    assert "events" in events
    assert isinstance(events["events"], list)
    assert any(e.get("type") == "add" for e in events["events"])
