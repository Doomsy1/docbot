"""Tests for the LangGraph agent exploration system."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from docbot.exploration.store import NotepadStore, NoteEntry
from docbot.exploration.prompts import build_system_prompt

# Guard for environments where langgraph is not installed.
try:
    import langgraph  # noqa: F401
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False

requires_langgraph = pytest.mark.skipif(
    not HAS_LANGGRAPH, reason="langgraph not installed"
)


# ---------------------------------------------------------------------------
# NotepadStore tests
# ---------------------------------------------------------------------------

class TestNotepadStore:
    def test_write_and_read(self):
        store = NotepadStore()
        result = store.write("arch.layers", "Three-tier architecture", author="root")
        assert "[root] Three-tier architecture" in result
        assert "Three-tier architecture" in store.read("arch.layers")

    def test_read_empty_topic(self):
        store = NotepadStore()
        result = store.read("nonexistent")
        assert "No entries" in result

    def test_list_topics_empty(self):
        store = NotepadStore()
        assert store.list_topics() == "No topics yet."

    def test_list_topics_with_entries(self):
        store = NotepadStore()
        store.write("arch.layers", "content1", author="a")
        store.write("patterns.mvc", "content2", author="b")
        topics = store.list_topics()
        assert "arch.layers" in topics
        assert "patterns.mvc" in topics

    def test_multiple_entries_same_topic(self):
        store = NotepadStore()
        store.write("arch", "first", author="agent1")
        store.write("arch", "second", author="agent2")
        result = store.read("arch")
        assert "[agent1] first" in result
        assert "[agent2] second" in result

    def test_serialize(self):
        store = NotepadStore()
        store.write("topic1", "content1", author="a")
        store.write("topic2", "content2", author="b")
        data = store.serialize()
        assert "topic1" in data
        assert "topic2" in data
        assert data["topic1"][0]["content"] == "content1"
        assert data["topic1"][0]["author"] == "a"

    def test_to_context_string(self):
        store = NotepadStore()
        store.write("arch", "overview here", author="root")
        ctx = store.to_context_string()
        assert "## arch" in ctx
        assert "overview here" in ctx

    def test_to_context_string_empty(self):
        store = NotepadStore()
        assert store.to_context_string() == "(notepad empty)"

    def test_to_context_string_truncation(self):
        store = NotepadStore()
        # Write a lot of content that exceeds max_chars.
        for i in range(100):
            store.write(f"topic_{i}", "x" * 100, author="a")
        ctx = store.to_context_string(max_chars=500)
        assert len(ctx) <= 600  # some slack for truncation marker

    def test_event_queue_receives_events(self):
        queue = asyncio.Queue()
        store = NotepadStore(event_queue=queue)
        store.write("test_topic", "content", author="agent")

        # Should have both notepad_created and notepad_write events.
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert len(events) == 2
        assert events[0]["type"] == "notepad_created"
        assert events[1]["type"] == "notepad_write"

    def test_event_queue_no_created_on_second_write(self):
        queue = asyncio.Queue()
        store = NotepadStore(event_queue=queue)
        store.write("test_topic", "first", author="a")
        # Drain queue.
        while not queue.empty():
            queue.get_nowait()

        store.write("test_topic", "second", author="b")
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        # Should only be notepad_write (no notepad_created for existing topic).
        assert len(events) == 1
        assert events[0]["type"] == "notepad_write"


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------

class TestPrompts:
    def test_build_system_prompt_root(self):
        prompt = build_system_prompt("Explore the repo")
        assert "Explore the repo" in prompt
        assert "root agent" in prompt

    def test_build_system_prompt_with_context(self):
        prompt = build_system_prompt("Explore auth module", "Parent found JWT usage")
        assert "Explore auth module" in prompt
        assert "Parent found JWT usage" in prompt
        assert "root agent" not in prompt


# ---------------------------------------------------------------------------
# Graph module tests (import-level)
# ---------------------------------------------------------------------------

class TestGraphImports:
    @requires_langgraph
    def test_agent_state_has_required_keys(self):
        from docbot.exploration.graph import AgentState
        # TypedDict keys.
        keys = list(AgentState.__annotations__.keys())
        assert "messages" in keys
        assert "agent_id" in keys
        assert "purpose" in keys
        assert "depth" in keys
        assert "max_depth" in keys
        assert "summary" in keys

    @requires_langgraph
    def test_build_graph_returns_compiled(self):
        """Verify build_graph compiles without error using a mock LLM."""
        from docbot.exploration.graph import build_graph
        from docbot.exploration.tools import create_tools
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = NotepadStore()
            tools = create_tools(repo_root=Path(tmp), store=store)

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm

            graph = build_graph(mock_llm, tools)
            # The compiled graph should have an invoke method.
            assert hasattr(graph, "invoke") or hasattr(graph, "ainvoke")


# ---------------------------------------------------------------------------
# Tools tests
# ---------------------------------------------------------------------------

class TestTools:
    @requires_langgraph
    def test_create_tools_returns_list(self):
        from docbot.exploration.tools import create_tools
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = NotepadStore()
            tools = create_tools(repo_root=Path(tmp), store=store)
            assert isinstance(tools, list)
            assert len(tools) == 7

    @requires_langgraph
    def test_tool_names(self):
        from docbot.exploration.tools import create_tools
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = NotepadStore()
            tools = create_tools(repo_root=Path(tmp), store=store)
            names = {t.name for t in tools}
            assert names == {
                "read_file", "list_directory", "read_notepad",
                "write_notepad", "list_topics", "delegate", "finish",
            }


# ---------------------------------------------------------------------------
# Callbacks tests
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_callback_instantiates(self):
        from docbot.exploration.callbacks import AgentEventCallback
        queue = asyncio.Queue()
        cb = AgentEventCallback(queue, "test-agent")
        assert cb.agent_id == "test-agent"

    @pytest.mark.asyncio
    async def test_on_llm_new_token(self):
        from docbot.exploration.callbacks import AgentEventCallback
        queue = asyncio.Queue()
        cb = AgentEventCallback(queue, "test-agent")
        await cb.on_llm_new_token("hello")
        event = queue.get_nowait()
        assert event["type"] == "llm_token"
        assert event["token"] == "hello"
        assert event["agent_id"] == "test-agent"

    @pytest.mark.asyncio
    async def test_on_tool_start(self):
        from docbot.exploration.callbacks import AgentEventCallback
        queue = asyncio.Queue()
        cb = AgentEventCallback(queue, "test-agent")
        await cb.on_tool_start({"name": "read_file"}, "test.py")
        event = queue.get_nowait()
        assert event["type"] == "tool_start"
        assert event["tool"] == "read_file"

    def test_callback_with_none_queue(self):
        from docbot.exploration.callbacks import AgentEventCallback
        # Should not raise.
        cb = AgentEventCallback(None, "test-agent")
        asyncio.run(cb.on_llm_new_token("test"))


# ---------------------------------------------------------------------------
# Merge function tests
# ---------------------------------------------------------------------------

class TestMergeAgentFindings:
    def test_merge_with_empty_store(self):
        from docbot.pipeline.orchestrator import _merge_agent_findings
        from docbot.models import ScopeResult

        store = NotepadStore()
        results = [
            ScopeResult(scope_id="s1", title="Test", paths=["a.py"], summary="original"),
        ]
        merged = _merge_agent_findings(results, store)
        # No changes when notepad is empty.
        assert merged[0].summary == "original"

    def test_merge_with_populated_store(self):
        from docbot.pipeline.orchestrator import _merge_agent_findings
        from docbot.models import ScopeResult

        store = NotepadStore()
        store.write("arch", "Found MVC pattern", author="root")

        results = [
            ScopeResult(scope_id="s1", title="Test", paths=["a.py"], summary="original"),
        ]
        merged = _merge_agent_findings(results, store)
        assert "Agent Exploration Findings" in merged[0].summary
        assert "Found MVC pattern" in merged[0].summary


# ---------------------------------------------------------------------------
# Notepad persistence tests
# ---------------------------------------------------------------------------

class TestNotepadPersistence:
    def test_persist_notepad(self, tmp_path):
        from docbot.pipeline.orchestrator import _persist_notepad

        store = NotepadStore()
        store.write("arch", "overview content", author="root")
        store.write("patterns", "singleton found", author="child1")

        _persist_notepad(store, tmp_path)

        import json
        data_path = tmp_path / "notepads" / "all_topics.json"
        assert data_path.exists()
        data = json.loads(data_path.read_text(encoding="utf-8"))
        assert "arch" in data
        assert "patterns" in data
        assert data["arch"][0]["content"] == "overview content"

    def test_persist_empty_notepad(self, tmp_path):
        from docbot.pipeline.orchestrator import _persist_notepad

        store = NotepadStore()
        _persist_notepad(store, tmp_path)
        # Should not create a file for empty notepad.
        assert not (tmp_path / "notepads" / "all_topics.json").exists()
