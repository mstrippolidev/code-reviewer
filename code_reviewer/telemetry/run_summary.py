"""
    Totals what model calls and finished agent runs cost: token usage, model turns and tool calls.
"""
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from pydantic import BaseModel

from code_reviewer.schemas.review import AgentOutput

STRUCTURED_OUTPUT_TOOL_NAME = AgentOutput.__name__


class ToolCallRecord(BaseModel):
    name: str
    failed: bool


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0


class RunSummary(BaseModel):
    model_turns: int = 0
    tool_calls: list[ToolCallRecord] = []


def usage_of(messages: Sequence[BaseMessage]) -> TokenUsage:
    """Totals the token usage reported by every AI message in one model response."""
    usage = TokenUsage()
    for message in messages:
        if isinstance(message, AIMessage):
            _add_message_usage(usage, message)
    return usage


def summarize_run(messages: Sequence[BaseMessage]) -> RunSummary:
    """Totals the model turns and tool calls found in one agent run's messages."""
    summary = RunSummary()
    for message in messages:
        if isinstance(message, AIMessage):
            summary.model_turns += 1
        elif isinstance(message, ToolMessage) and message.name != STRUCTURED_OUTPUT_TOOL_NAME:
            summary.tool_calls.append(ToolCallRecord(name=message.name or "unknown", failed=message.status == "error"))
    return summary


def _add_message_usage(usage: TokenUsage, message: AIMessage) -> None:
    """Adds one AI message's reported token usage to the total."""
    reported = message.usage_metadata or {}
    usage.input_tokens += reported.get("input_tokens", 0)
    usage.output_tokens += reported.get("output_tokens", 0)
    usage.reasoning_tokens += reported.get("output_token_details", {}).get("reasoning", 0)
    usage.cached_input_tokens += reported.get("input_token_details", {}).get("cache_read", 0)
