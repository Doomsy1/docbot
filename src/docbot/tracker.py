"""Thread-safe pipeline state tracker for visualization."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentState(Enum):
    pending = "pending"
    waiting = "waiting"
    running = "running"
    done = "done"
    error = "error"


@dataclass
class AgentNode:
    id: str
    name: str
    state: AgentState = AgentState.pending
    parent_id: str | None = None
    children_ids: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    detail: str = ""


class PipelineTracker:
    """Thread-safe tracker that stores the agent tree and serves snapshots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, AgentNode] = {}
        self._root_id: str | None = None

    def add_node(self, node_id: str, name: str, parent_id: str | None = None) -> None:
        with self._lock:
            node = AgentNode(id=node_id, name=name, parent_id=parent_id)
            self._nodes[node_id] = node
            if parent_id is None:
                self._root_id = node_id
            elif parent_id in self._nodes:
                self._nodes[parent_id].children_ids.append(node_id)

    def set_state(
        self, node_id: str, state: AgentState, detail: str = ""
    ) -> None:
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return
            node.state = state
            node.detail = detail
            now = time.monotonic()
            if state == AgentState.running and node.started_at is None:
                node.started_at = now
            if state in (AgentState.done, AgentState.error):
                node.finished_at = now

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            nodes = []
            for n in self._nodes.values():
                if n.finished_at and n.started_at:
                    elapsed = round(n.finished_at - n.started_at, 1)
                elif n.started_at:
                    elapsed = round(now - n.started_at, 1)
                else:
                    elapsed = 0.0
                nodes.append(
                    {
                        "id": n.id,
                        "name": n.name,
                        "state": n.state.value,
                        "parent": n.parent_id,
                        "children": list(n.children_ids),
                        "elapsed": elapsed,
                        "detail": n.detail,
                    }
                )
            return {"nodes": nodes, "root": self._root_id}


class NoOpTracker:
    """Drop-in replacement that does nothing; used when --visualize is off."""

    def add_node(self, node_id: str, name: str, parent_id: str | None = None) -> None:
        pass

    def set_state(
        self, node_id: str, state: AgentState, detail: str = ""
    ) -> None:
        pass

    def snapshot(self) -> dict[str, Any]:
        return {"nodes": [], "root": None}
