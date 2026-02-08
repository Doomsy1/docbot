"""Tests for pipeline event APIs."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from docbot.models import DocsIndex
from docbot.pipeline.tracker import PipelineTracker
from docbot.web import server


def _write_index(docbot_dir: Path, repo_root: Path) -> None:
    index = DocsIndex(
        repo_path=str(repo_root),
        generated_at="2026-02-07T00:00:00Z",
        scopes=[],
        languages=[],
    )
    (docbot_dir / "docs_index.json").write_text(
        index.model_dump_json(indent=2), encoding="utf-8"
    )


def test_pipeline_api_returns_latest_run_events(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    docbot_dir = repo_root / ".docbot"
    run_id = "20260207T000000Z_abcd12"
    run_history_dir = docbot_dir / "history" / run_id
    run_history_dir.mkdir(parents=True)
    repo_root.mkdir(exist_ok=True)

    _write_index(docbot_dir, repo_root)
    (docbot_dir / "state.json").write_text(
        json.dumps({"last_run_id": run_id, "scope_file_map": {}}, indent=2),
        encoding="utf-8",
    )
    (run_history_dir / "pipeline_events.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "events": [{"type": "tool_call", "node_id": "scope.auth"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    server._run_dir = docbot_dir
    server._index_cache = None
    server._search_index_cache = None

    client = TestClient(server.app)
    response = client.get("/api/pipeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run_id
    assert payload["events"][0]["type"] == "tool_call"


def test_agent_stream_returns_done_event_when_no_live_queue() -> None:
    server._live_event_queue = None
    client = TestClient(server.app)

    response = client.get("/api/agent-stream")

    assert response.status_code == 200
    assert "event: done" in response.text
    assert '{"no_agents": true}' in response.text


def test_agent_state_falls_back_to_persisted_json(tmp_path: Path) -> None:
    run_dir = tmp_path / ".docbot"
    run_dir.mkdir(parents=True)
    persisted = {
        "agents": {
            "agent-root": {
                "agent_id": "agent-root",
                "parent_id": None,
                "purpose": "Explore project",
                "depth": 0,
                "status": "done",
                "text": "summary",
                "tools": [],
            }
        },
        "notepads": {"arch": [{"content": "layered", "author": "agent-root"}]},
    }
    (run_dir / "agent_state.json").write_text(
        json.dumps(persisted, indent=2), encoding="utf-8"
    )

    server._run_dir = run_dir
    server._agent_state_snapshot = {"agents": {}, "notepads": {}}
    client = TestClient(server.app)

    response = client.get("/api/agent-state")

    assert response.status_code == 200
    assert response.json() == persisted


def test_pipeline_api_falls_back_to_live_tracker_when_no_saved_events(tmp_path: Path) -> None:
    run_dir = tmp_path / "no-events-yet"
    run_dir.mkdir(parents=True)

    tracker = PipelineTracker()
    tracker.set_run_id("live-run")
    tracker.add_node("orchestrator", "Orchestrator")

    server._run_dir = run_dir
    server._live_pipeline_tracker = tracker
    client = TestClient(server.app)

    response = client.get("/api/pipeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "live-run"
    assert len(payload["events"]) >= 1
