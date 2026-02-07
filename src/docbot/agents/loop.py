"""Agent loop -- minimal async agent execution loop."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
                summary = call.args.get("summary", "")
                if summary:
                    return summary
                return _extract_summary(response)
            
            # Execute tool
            result = await toolkit.execute(call.name, call.args)
            
            # Add tool result to messages
            messages.append({
                "role": "user",
                "content": f"Tool '{call.name}' result:\n{result}"
            })
    
    logger.warning("[%s] Max steps reached", agent_id)
    return f"(Agent reached max steps without finishing. Last response excerpt: {response[:500]}...)"


def _build_tool_instruction() -> str:
    """Build instruction text for tool usage."""
    return """
## Available Tools

To use a tool, respond with a JSON code block:

```json
{"tool": "tool_name", "args": {"arg1": "value1", ...}}
```

**Tools:**

1. `read_file(path)` - Read source code from a file (use sparingly, prefer subagents for complex files)
2. `read_symbol(file, symbol)` - Read a specific function/class definition
3. `write_notepad(key, content)` - Record a finding (use dot notation: patterns.X, api.X)
4. `spawn_subagent(agent_type, target, task)` - **PREFERRED**: Spawn file/symbol subagent for deep analysis
   - agent_type: "file" or "symbol"
   - target: file path, or "file:symbol_name" for symbols
   - task: description of what to analyze
5. `finish(summary)` - Complete with final summary (call when done)

**IMPORTANT**: For scopes with 3+ files, spawn FileAgents rather than reading everything yourself. This enables parallel analysis and better coverage.
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
