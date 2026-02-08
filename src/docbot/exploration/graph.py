"""LangGraph StateGraph definition for recursive agent exploration.

This module defines the agent state schema and builds the compiled ReAct
graph used by ``run_agent_exploration()`` in the parent package.  The graph
follows the standard ReAct loop:

    agent --[tool_calls]--> tools ---> agent
    agent --[no tool_calls]--> END

The ``AgentState`` TypedDict carries all per-invocation context that the
agent and tool nodes need: identity, purpose, depth limits, accumulated
messages, and the final summary produced by the ``finish`` tool.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """Shared state that flows through every node in the agent graph.

    Fields
    ------
    messages:
        The conversation history.  Uses the ``add_messages`` reducer so that
        each node can *append* messages rather than replacing the full list.
    agent_id:
        Unique identifier for this agent instance (e.g. ``"root"``,
        ``"scope:auth"``).  Used for logging and event tracking.
    parent_id:
        The ``agent_id`` of the agent that spawned this one, or ``None``
        for the root agent.
    purpose:
        A short natural-language description of why this agent was spawned.
        Injected into the system prompt so the LLM knows its mission.
    context_packet:
        Condensed knowledge passed down from the parent agent.  Empty
        string for the root agent.
    repo_root:
        Absolute path to the repository being documented.
    scope_files:
        List of repo-relative file paths this agent is responsible for.
        May be empty for the root agent (which discovers files on its own).
    depth:
        Current recursion depth (0 for the root agent).
    max_depth:
        Maximum allowed depth.  Agents at ``depth >= max_depth`` must not
        spawn further sub-agents.
    summary:
        Populated by the ``finish`` tool when the agent completes its
        analysis.  Empty string until then.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    agent_id: str
    parent_id: str | None
    purpose: str
    context_packet: str
    repo_root: str
    scope_files: list[str]
    depth: int
    max_depth: int
    summary: str


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def _agent_node(state: AgentState, llm_with_tools: Any) -> dict:
    """Invoke the LLM with the current message history and bound tools.

    Returns a dict containing the new assistant message so the ``add_messages``
    reducer appends it to the conversation.
    """
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def _should_continue(state: AgentState) -> str:
    """Conditional edge: route to the tools node or to END.

    If the last message from the LLM contains tool calls, we route to the
    ``tools`` node so they can be executed.  Otherwise the agent is done
    and we route to ``END``.
    """
    last_message = state["messages"][-1]

    # ``AIMessage.tool_calls`` is a list; non-empty means the LLM wants
    # to invoke one or more tools before producing a final answer.
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(
    llm: Any,
    tools: list[Any],
    tool_choice: Any = None,
) -> Any:
    """Construct and compile the ReAct agent graph.

    Parameters
    ----------
    llm:
        A ``ChatOpenAI`` (or compatible) LLM instance.  The tools will be
        bound to it via ``llm.bind_tools()``.
    tools:
        A list of LangChain tool objects (``@tool``-decorated functions or
        ``BaseTool`` subclasses) that the agent can invoke.

    Returns
    -------
    CompiledGraph
        A compiled LangGraph ``StateGraph`` ready for ``.invoke()`` or
        ``.ainvoke()``.
    """
    # Bind tools so the LLM emits structured tool-call messages.
    if tool_choice is None:
        llm_with_tools = llm.bind_tools(tools)
    else:
        llm_with_tools = llm.bind_tools(tools, tool_choice=tool_choice)

    # Create the graph with our state schema.
    graph = StateGraph(AgentState)

    # -- Nodes ---------------------------------------------------------------
    # The agent node calls the LLM.  We use a lambda to close over the
    # bound LLM instance since LangGraph node functions receive only the
    # state dict.
    graph.add_node(
        "agent",
        lambda state: _agent_node(state, llm_with_tools),
    )

    # The tools node executes whatever tool calls the LLM produced.
    graph.add_node("tools", ToolNode(tools))

    # -- Edges ---------------------------------------------------------------
    # Entry point: always start at the agent node.
    graph.set_entry_point("agent")

    # After the agent node, decide whether to execute tools or finish.
    graph.add_conditional_edges("agent", _should_continue, {
        "tools": "tools",
        END: END,
    })

    # After tool execution, loop back to the agent so it can inspect results
    # and decide its next action.
    graph.add_edge("tools", "agent")

    return graph.compile()
