"""
    Tests for the output token cap: the provider parameter name, and failing a reply cut off at the cap.
"""
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from code_reviewer.agents.llm.call_observer import classify_llm_error
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.agents.llm.output_cap import OutputTruncatedError, RaiseOnTruncatedOutput
from code_reviewer.config.settings import get_settings


def _result(generation_info: dict | None = None, response_metadata: dict | None = None) -> LLMResult:
    message = AIMessage(content="{", response_metadata=response_metadata or {})
    return LLMResult(generations=[[ChatGeneration(message=message, generation_info=generation_info)]])


def test_the_default_cap_is_sixty_thousand_tokens() -> None:
    """Verify the default sits under the smallest limit of any model in use (65,535)."""
    assert get_settings().llm_max_output_tokens == 60000


def test_openrouter_names_the_cap_max_tokens() -> None:
    """Verify OpenRouter and Bedrock get LangChain's standard parameter."""
    assert OpenRouter()._output_limit_kwargs(60000) == {"max_tokens": 60000}


def test_ollama_names_the_cap_num_predict() -> None:
    """Verify Ollama gets its own parameter, since ChatOllama has no max_tokens."""
    assert OllamaLLM()._output_limit_kwargs(60000) == {"num_predict": 60000}


def test_a_built_ollama_model_carries_the_cap_and_the_truncation_check() -> None:
    """Verify create_raw_model wires both, so every caller that builds a model gets them."""
    model = OllamaLLM().create_raw_model()

    assert model.num_predict == get_settings().llm_max_output_tokens
    assert any(isinstance(handler, RaiseOnTruncatedOutput) for handler in model.callbacks)


@pytest.mark.parametrize(
    ("generation_info", "response_metadata"),
    [
        (None, {"finish_reason": "length"}),
        ({"finish_reason": "length"}, None),
        (None, {"stopReason": "max_tokens"}),
        (None, {"stop_reason": "max_tokens"}),
        (None, {"done_reason": "length"}),
    ],
)
def test_a_reply_cut_off_at_the_cap_raises(generation_info: dict | None, response_metadata: dict | None) -> None:
    """Verify each provider's way of reporting a cut-off is recognised."""
    with pytest.raises(OutputTruncatedError):
        RaiseOnTruncatedOutput().on_llm_end(_result(generation_info, response_metadata))


@pytest.mark.parametrize("reason", ["stop", "tool_calls", "end_turn"])
def test_a_reply_that_finished_normally_does_not_raise(reason: str) -> None:
    """Verify only a cut-off fails, not every stop reason."""
    RaiseOnTruncatedOutput().on_llm_end(_result(None, {"finish_reason": reason}))


def test_the_callback_is_not_swallowed_by_langchain() -> None:
    """Verify raise_error is on, since LangChain ignores an exception from a callback otherwise."""
    assert RaiseOnTruncatedOutput.raise_error is True


def test_a_cut_off_is_counted_under_its_own_cause() -> None:
    """Verify llm.call.errors can tell a cut-off from a timeout or a schema failure."""
    assert classify_llm_error(OutputTruncatedError("cut off")) == "output_truncated"
