"""
    Reads the reasoning a model sent with a reply.
"""
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage

REASONING_BLOCK_TYPES = ("reasoning", "thinking")
REASONING_BLOCK_KEYS = ("reasoning", "thinking", "text")


def reasoning_of(message: BaseMessage) -> str | None:
    """The reasoning langchain_openrouter stores in additional_kwargs, else any reasoning content blocks."""
    stored = message.additional_kwargs.get("reasoning_content")
    if stored:
        return str(stored)
    if not isinstance(message.content, list):
        return None
    blocks = [_block_reasoning(part) for part in message.content if _is_reasoning_block(part)]
    joined = "\n".join(block for block in blocks if block)
    return joined or None


def has_reasoning(messages: Sequence[BaseMessage]) -> bool:
    """True when any message of a run carries reasoning."""
    return any(reasoning_of(message) for message in messages)


def _is_reasoning_block(part: str | dict[str, Any]) -> bool:
    return isinstance(part, dict) and part.get("type") in REASONING_BLOCK_TYPES


def _block_reasoning(block: dict[str, Any]) -> str:
    return next((str(block[key]) for key in REASONING_BLOCK_KEYS if block.get(key)), "")
