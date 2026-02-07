"""Agents module -- recursive exploration agents with tools and notepads."""

from __future__ import annotations

from .notepad import Notepad, NoteEntry
from .tools import AgentToolkit, TOOL_DEFINITIONS, ROOT_TOOL_DEFINITIONS
from .loop import run_agent_loop, run_agent_loop_streaming
from .scope_agent import run_scope_agent

__all__ = [
    "Notepad",
    "NoteEntry",
    "AgentToolkit",
    "TOOL_DEFINITIONS",
    "ROOT_TOOL_DEFINITIONS",
    "run_agent_loop",
    "run_agent_loop_streaming",
    "run_scope_agent",
]
