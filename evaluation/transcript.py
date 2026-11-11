"""
    What the model said during one agent run, as plain data a report can store.
"""
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from pydantic import BaseModel, Field, computed_field

from code_reviewer.agents.reasoning import reasoning_of

ROLE_BY_MESSAGE_TYPE = {"human": "user", "ai": "assistant", "tool": "tool", "system": "system"}
REPLY_DETAIL_KEYS = ("model_name", "finish_reason", "native_finish_reason", "system_fingerprint")


class TranscriptToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


class TranscriptMessage(BaseModel):
    role: str
    text: str
    reasoning: str | None = Field(default=None, exclude=True)
    tool_calls: list[TranscriptToolCall] = []
    tool_name: str | None = None
    reply_details: dict[str, str] = {}

    @computed_field
    @property
    def reasoning_characters(self) -> int:
        """Length of the reasoning, which is kept out of every saved report but the reasoning log."""
        return len(self.reasoning or "")


class RunTranscript(BaseModel):
    messages: list[TranscriptMessage] = []

    @computed_field
    @property
    def has_reasoning(self) -> bool:
        """False when the model sent no reasoning, so an empty transcript is not mistaken for a capture failure."""
        return any(message.reasoning for message in self.messages)


def transcript_of(messages: Sequence[BaseMessage]) -> RunTranscript:
    """Converts the messages of one finished run, in order."""
    return RunTranscript(messages=[_transcript_message(message) for message in messages])


def _transcript_message(message: BaseMessage) -> TranscriptMessage:
    return TranscriptMessage(
        role=ROLE_BY_MESSAGE_TYPE.get(message.type, message.type),
        text=_text_of(message.content),
        reasoning=reasoning_of(message),
        tool_calls=_tool_calls_of(message),
        tool_name=message.name if isinstance(message, ToolMessage) else None,
        reply_details=_reply_details_of(message),
    )


def _reply_details_of(message: BaseMessage) -> dict[str, str]:
    """The model and finish details the provider sent back with a reply; empty for any other message."""
    if not isinstance(message, AIMessage):
        return {}
    metadata = message.response_metadata
    return {key: str(metadata[key]) for key in REPLY_DETAIL_KEYS if metadata.get(key)}


def _text_of(content: str | list[str | dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    parts = [part if isinstance(part, str) else part.get("text", "") for part in content if _is_text_part(part)]
    return "\n".join(parts)


def _is_text_part(part: str | dict[str, Any]) -> bool:
    return isinstance(part, str) or part.get("type") == "text"


def _tool_calls_of(message: BaseMessage) -> list[TranscriptToolCall]:
    if not isinstance(message, AIMessage):
        return []
    return [TranscriptToolCall(name=call["name"], arguments=call["args"]) for call in message.tool_calls]
