"""
    Stops a model call whose reply was cut off at the output token cap, before anything tries to parse it.
"""
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import ChatGeneration, Generation, LLMResult

_STOP_REASON_KEYS = ("finish_reason", "stop_reason", "stopReason", "done_reason")
_TRUNCATED_STOP_REASONS = frozenset({"length", "max_tokens"})


class OutputTruncatedError(Exception):
    """Raised when a model call ended because it reached the output token cap."""


class RaiseOnTruncatedOutput(BaseCallbackHandler):
    """Raises OutputTruncatedError when a finished call stopped at the token cap.

    raise_error is True because LangChain swallows an exception raised in a callback otherwise, and a cut-off
    reply must not reach the structured-output parser, which would call it a schema failure and retry it.
    """

    raise_error = True

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for generations in response.generations:
            for generation in generations:
                if _stop_reasons_of(generation) & _TRUNCATED_STOP_REASONS:
                    raise OutputTruncatedError("The model reply was cut off at the output token cap.")


def _stop_reasons_of(generation: Generation) -> set[str]:
    """Every stop reason the generation carries; providers name the key differently."""
    sources = [generation.generation_info or {}]
    if isinstance(generation, ChatGeneration):
        sources.append(generation.message.response_metadata)
    return {str(source[key]) for source in sources for key in _STOP_REASON_KEYS if key in source}
