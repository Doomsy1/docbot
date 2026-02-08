"""Agents module -- recursive exploration agents with tools and notepads.

.. deprecated::
    This module is superseded by ``docbot.exploration``, which uses LangGraph
    for agent orchestration.  This module is retained for backward compatibility
    and reference only.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "docbot.agents is deprecated. Use docbot.exploration instead.",
    DeprecationWarning,
    stacklevel=2,
)

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
