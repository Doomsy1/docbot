"""Agent loop -- minimal async agent execution loop."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..llm import LLMClient
    from .tools import AgentToolkit

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Parsed tool call from LLM response."""
    name: str
    args: dict


def parse_tool_calls(response: str) -> list[ToolCall]:
    """Parse tool calls from LLM response.
    
    Supports two formats:
    1. OpenAI function calling format (JSON with tool_calls array)
    2. Fallback: JSON code blocks with {"tool": "name", "args": {...}}
    """
    calls: list[ToolCall] = []
    
    # Try to parse as JSON first (OpenAI format might return structured data)
    try:
        data = json.loads(response)
        if isinstance(data, dict):
            # Check for tool_calls array (standard format)
            if "tool_calls" in data:
                for tc in data["tool_calls"]:
                    func = tc.get("function", {})
                    calls.append(ToolCall(
                        name=func.get("name", ""),
                        args=json.loads(func.get("arguments", "{}"))
                    ))
                return calls
            # Check for direct tool call format
            if "tool" in data and "args" in data:
                calls.append(ToolCall(name=data["tool"], args=data["args"]))
                return calls
    except json.JSONDecodeError:
        pass
    
    # Fallback: look for JSON code blocks
    json_pattern = r'```(?:json)?\s*(\{[^`]+\})\s*```'
    for match in re.finditer(json_pattern, response, re.DOTALL):
        try:
            data = json.loads(match.group(1))
            if "tool" in data and "args" in data:
                calls.append(ToolCall(name=data["tool"], args=data["args"]))
            elif "name" in data and "arguments" in data:
                args = data["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)
                calls.append(ToolCall(name=data["name"], args=args))
        except json.JSONDecodeError:
            continue
    
    # Last resort: look for inline JSON
    if not calls:
        inline_pattern = r'\{"tool"\s*:\s*"(\w+)"\s*,\s*"args"\s*:\s*(\{[^}]+\})\}'
        for match in re.finditer(inline_pattern, response):
            try:
                calls.append(ToolCall(
                    name=match.group(1),
                    args=json.loads(match.group(2))
                ))
            except json.JSONDecodeError:
                continue
    
    return calls


async def run_agent_loop(
    llm_client: LLMClient,
    system_prompt: str,
    initial_context: str,
    toolkit: AgentToolkit,
    max_steps: int = 15,
    agent_id: str = "",
    tracker: object | None = None,
    tracker_node_id: str = "",
) -> str:
    """Run agent loop until 'finish' tool is called or max_steps reached.
    
    The agent receives tool definitions and iteratively calls tools to gather
    information, then calls 'finish' with a summary.
    
    Returns the final summary from the 'finish' call.
    """
    from .tools import TOOL_DEFINITIONS
    
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial_context},
    ]
    
    # Build tool instruction for models that don't have native function calling
    tool_instruction = _build_tool_instruction()
    messages[0]["content"] += "\n\n" + tool_instruction
    
    for step in range(max_steps):
        logger.debug("[%s] Step %d/%d", agent_id, step + 1, max_steps)
        
        # Call LLM
        try:
            response = await llm_client.chat(messages)
        except Exception as e:
            logger.error("[%s] LLM call failed: %s", agent_id, e)
            return f"(Agent error: LLM call failed - {e})"
        
        # Add assistant response to history
        messages.append({"role": "assistant", "content": response})

        # Record LLM text to tracker
        if tracker and tracker_node_id and response:
            try:
                tracker.append_text(tracker_node_id, response)  # type: ignore[union-attr]
            except Exception:
                pass

        # Parse tool calls
        tool_calls = parse_tool_calls(response)
        
        if not tool_calls:
            # No tool call found - check if response looks like a final summary
            if "finish" in response.lower() or step == max_steps - 1:
                # Extract summary from natural language response
                return _extract_summary(response)
            
            # Prompt for tool use
            messages.append({
                "role": "user",
                "content": "Please use one of the available tools to continue your analysis, or call 'finish' with your summary."
            })
            continue
        
        # Execute tool calls
        for call in tool_calls:
            logger.debug("[%s] Tool call: %s(%s)", agent_id, call.name, call.args)
            
            if call.name == "finish":
                await toolkit.flush_subagents()
                summary = call.args.get("summary", "")
                if summary:
                    return summary
                return _extract_summary(response)
            
            # Execute tool
            result = await toolkit.execute(call.name, call.args)

            # Record tool call to tracker
            if tracker and tracker_node_id:
                try:
                    tracker.record_tool_call(tracker_node_id, call.name, call.args, result[:200])  # type: ignore[union-attr]
                except Exception:
                    pass

            # Add tool result to messages
            messages.append({
                "role": "user",
                "content": f"Tool '{call.name}' result:\n{result}"
            })
    
    await toolkit.flush_subagents()
    logger.warning("[%s] Max steps reached", agent_id)
    return f"(Agent reached max steps without finishing. Last response excerpt: {response[:500]}...)"


def _build_tool_instruction() -> str:
    """Build instruction text for tool usage."""
    return """
## Tool Usage

Respond with a JSON code block to call a tool:

```json
{"tool": "tool_name", "args": {"arg1": "value1"}}
```

**Tools:**
1. `read_file(path)` -- Read a source file. Use for short/simple files you can \
analyze yourself.
2. `read_symbol(file, symbol)` -- Read a specific function or class definition.
3. `write_notepad(key, content)` -- Record a finding. Use dot-notation keys \
(e.g. patterns.auth, api.login, architecture.overview).
4. `spawn_subagent(agent_type, target, task)` -- Delegate deep analysis. \
agent_type is "file" or "symbol"; target is a file path (or "file:symbol" for \
symbol agents); task describes what to analyze.
5. `finish(summary)` -- Return your final summary. Call this when done.

**Workflow**: Orient yourself with extraction data, read or delegate files as \
appropriate, record findings, then finish.
"""


def _extract_summary(response: str) -> str:
    """Extract summary from a natural language response."""
    # Look for explicit summary markers
    markers = ["summary:", "in summary:", "to summarize:", "conclusion:"]
    lower = response.lower()
    for marker in markers:
        idx = lower.find(marker)
        if idx != -1:
            return response[idx + len(marker):].strip()

    # Return last paragraph as summary
    paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
    if paragraphs:
        return paragraphs[-1]

    return response[:1000]


# ---------------------------------------------------------------------------
# Streaming agent loop
# ---------------------------------------------------------------------------

# Tools that can execute immediately mid-stream (they just schedule async tasks)
_SPAWN_TOOLS = {"spawn_subagent", "delegate_folder"}


async def run_agent_loop_streaming(
    llm_client: LLMClient,
    system_prompt: str,
    initial_context: str,
    toolkit: AgentToolkit,
    tool_definitions: list[dict] | None = None,
    max_steps: int = 15,
    agent_id: str = "",
    on_text_delta: Callable[[str], None] | None = None,
    on_tool_start: Callable[[str, dict], None] | None = None,
    tracker: object | None = None,
    tracker_node_id: str = "",
) -> str:
    """Streaming agent loop that executes spawn tools mid-stream.

    Like ``run_agent_loop`` but uses ``llm_client.stream_chat()`` and fires
    spawn-type tool calls (``delegate_folder``, ``spawn_subagent``) as soon as
    their JSON arguments are complete, rather than waiting for the full
    response.  Other tools are queued and executed after the stream ends.

    Parameters
    ----------
    tool_definitions:
        OpenAI-format tool defs to pass to the LLM.  Defaults to the
        standard ``TOOL_DEFINITIONS`` if not provided.
    on_text_delta:
        Called with each text chunk as it arrives.
    on_tool_start:
        Called when a tool call is detected (name, parsed args).
    """
    if tool_definitions is None:
        from .tools import TOOL_DEFINITIONS
        tool_definitions = TOOL_DEFINITIONS

    tool_instruction = _build_tool_instruction_streaming(tool_definitions)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt + "\n\n" + tool_instruction},
        {"role": "user", "content": initial_context},
    ]

    for step in range(max_steps):
        logger.debug("[%s] Streaming step %d/%d", agent_id, step + 1, max_steps)

        # Accumulate full text and tool calls from stream
        full_text = ""
        tool_calls: list[ToolCall] = []
        queued_tool_results: list[tuple[str, dict]] = []  # (name, args) for non-spawn
        finish_called = False
        finish_summary = ""

        try:
            async for delta in llm_client.stream_chat(messages, tools=tool_definitions):
                # Content delta
                if delta.content:
                    full_text += delta.content
                    if on_text_delta:
                        on_text_delta(delta.content)
                    if tracker and tracker_node_id:
                        try:
                            tracker.append_text(tracker_node_id, delta.content)  # type: ignore[union-attr]
                        except Exception:
                            pass

        except Exception as e:
            logger.error("[%s] Stream failed: %s", agent_id, e)
            return f"(Agent error: stream failed - {e})"

        # Backboard has no native tool call streaming — parse from text
        if not tool_calls and full_text:
            text_calls = parse_tool_calls(full_text)
            for tc in text_calls:
                if on_tool_start:
                    on_tool_start(tc.name, tc.args)

                if tc.name == "finish":
                    finish_called = True
                    finish_summary = tc.args.get("summary", "")
                elif tc.name in _SPAWN_TOOLS:
                    result = await toolkit.execute(tc.name, tc.args)
                    if tracker and tracker_node_id:
                        try:
                            tracker.record_tool_call(tracker_node_id, tc.name, tc.args, result[:200])  # type: ignore[union-attr]
                        except Exception:
                            pass
                else:
                    queued_tool_results.append((tc.name, tc.args))
                tool_calls.append(tc)

        # Execute queued non-spawn tools
        tool_result_msgs: list[str] = []
        for name, args in queued_tool_results:
            logger.debug("[%s] Tool call: %s(%s)", agent_id, name, args)
            result = await toolkit.execute(name, args)
            if tracker and tracker_node_id:
                try:
                    tracker.record_tool_call(tracker_node_id, name, args, result[:200])  # type: ignore[union-attr]
                except Exception:
                    pass
            tool_result_msgs.append(f"Tool '{name}' result:\n{result}")

        # Handle finish
        if finish_called:
            await toolkit.flush_subagents()
            if finish_summary:
                return finish_summary
            return _extract_summary(full_text) if full_text else "(Agent finished without summary)"

        # Build assistant message for history
        # Construct a representation that includes both text and tool usage
        assistant_content = full_text
        if queued_tool_results:
            completed_names = [f"{n}({json.dumps(a)[:80]})" for n, a in queued_tool_results]
            assistant_content += "\n\n[Tools called: " + ", ".join(completed_names) + "]"
        messages.append({"role": "assistant", "content": assistant_content or "(tool calls only)"})

        # Add tool results
        if tool_result_msgs:
            messages.append({
                "role": "user",
                "content": "\n\n---\n\n".join(tool_result_msgs),
            })

        # If no tool calls at all, prompt for tool use
        if not tool_calls and not full_text.strip():
            messages.append({
                "role": "user",
                "content": "Please use one of the available tools to continue your analysis, or call 'finish' with your summary.",
            })

    await toolkit.flush_subagents()
    logger.warning("[%s] Max steps reached (streaming)", agent_id)
    return f"(Agent reached max steps. Last text: {full_text[:500]}...)" if full_text else "(Max steps reached)"


def _build_tool_instruction_streaming(tool_defs: list[dict]) -> str:
    """Build a brief tool instruction for models that also receive native tool defs."""
    names = [t["function"]["name"] for t in tool_defs if "function" in t]
    return (
        "You have access to the following tools: " + ", ".join(names) + ". "
        "Use them via the function calling interface. "
        "Call 'finish' with a comprehensive summary when your analysis is complete."
    )
