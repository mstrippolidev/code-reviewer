"""
    Totals what one finished agent run cost: model turns, token usage and tool calls.
"""
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from pydantic import BaseModel


class ToolCallRecord(BaseModel):
    name: str
    failed: bool


class RunSummary(BaseModel):
    model_turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    tool_calls: list[ToolCallRecord] = []


def summarize_run(messages: Sequence[BaseMessage]) -> RunSummary:
    """Totals the tokens, model turns and tool calls found in one agent run's messages."""
    summary = RunSummary()
    for message in messages:
        if isinstance(message, AIMessage):
            _add_model_turn(summary, message)
        elif isinstance(message, ToolMessage):
            summary.tool_calls.append(ToolCallRecord(name=message.name or "unknown", failed=message.status == "error"))
    return summary


def _add_model_turn(summary: RunSummary, message: AIMessage) -> None:
    """Adds one model turn and its reported token usage to the summary."""
    usage = message.usage_metadata or {}
    summary.model_turns += 1
    summary.input_tokens += usage.get("input_tokens", 0)
    summary.output_tokens += usage.get("output_tokens", 0)
    summary.reasoning_tokens += usage.get("output_token_details", {}).get("reasoning", 0)
    summary.cached_input_tokens += usage.get("input_token_details", {}).get("cache_read", 0)
