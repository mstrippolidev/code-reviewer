"""
    Tests for dedupe_tool_calls and retry_missing_structured_output. No LLM
    involved — pure logic against hand-built middleware requests.
"""
import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage

from code_reviewer.agents.llm.middleware import (
    StructuredOutputNotCalledError,
    _already_called,
    dedupe_tool_calls,
    retry_missing_structured_output,
)

FILE_PATH_ARGS = {"file_path": "infra/db.py"}


def _request(tool_call: dict, messages: list) -> ToolCallRequest:
    return ToolCallRequest(tool_call=tool_call, tool=None, state={"messages": messages}, runtime=None)


def test_first_call_is_not_a_self_match() -> None:
    """Regression: the message carrying the current call is already
    committed to state by the time this runs. Without excluding it by id,
    every call would match itself and never actually execute."""
    call = {"name": "get_file_chunks", "args": FILE_PATH_ARGS, "id": "call_1"}
    messages = [AIMessage(content="", tool_calls=[call])]

    assert _already_called(_request(call, messages)) is False


def test_genuine_earlier_repeat_is_detected() -> None:
    earlier = {"name": "get_file_chunks", "args": FILE_PATH_ARGS, "id": "call_1"}
    current = {"name": "get_file_chunks", "args": FILE_PATH_ARGS, "id": "call_2"}
    messages = [
        AIMessage(content="", tool_calls=[earlier]),
        AIMessage(content="", tool_calls=[current]),
    ]

    assert _already_called(_request(current, messages)) is True


def test_same_name_different_args_is_not_a_repeat() -> None:
    earlier = {"name": "get_file_chunks", "args": {"file_path": "a.py"}, "id": "call_1"}
    current = {"name": "get_file_chunks", "args": {"file_path": "b.py"}, "id": "call_2"}
    messages = [
        AIMessage(content="", tool_calls=[earlier]),
        AIMessage(content="", tool_calls=[current]),
    ]

    assert _already_called(_request(current, messages)) is False


def test_argument_key_order_does_not_defeat_matching() -> None:
    earlier = {"name": "get_file_chunks", "args": {"file_path": "a.py", "imported_symbol_name": "X"}, "id": "call_1"}
    current = {"name": "get_file_chunks", "args": {"imported_symbol_name": "X", "file_path": "a.py"}, "id": "call_2"}
    messages = [
        AIMessage(content="", tool_calls=[earlier]),
        AIMessage(content="", tool_calls=[current]),
    ]

    assert _already_called(_request(current, messages)) is True


def test_dedupe_short_circuits_without_calling_the_handler() -> None:
    earlier = {"name": "get_file_chunks", "args": FILE_PATH_ARGS, "id": "call_1"}
    current = {"name": "get_file_chunks", "args": FILE_PATH_ARGS, "id": "call_2"}
    messages = [
        AIMessage(content="", tool_calls=[earlier]),
        AIMessage(content="", tool_calls=[current]),
    ]
    handler_calls = []

    result = dedupe_tool_calls.wrap_tool_call(_request(current, messages), lambda request: handler_calls.append(request))

    assert handler_calls == []
    assert result.tool_call_id == "call_2"
    assert "already called this tool" in result.content


def test_dedupe_calls_the_handler_when_not_a_repeat() -> None:
    call = {"name": "get_file_chunks", "args": FILE_PATH_ARGS, "id": "call_1"}
    messages = [AIMessage(content="", tool_calls=[call])]

    result = dedupe_tool_calls.wrap_tool_call(_request(call, messages), lambda request: "real result")

    assert result == "real result"


def _model_request() -> ModelRequest:
    return ModelRequest(model=None, messages=[])


def _no_tool_call_response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="Here is my review in words.")])


def _tool_call_response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="", tool_calls=[{"name": "get_file_chunks", "args": {}, "id": "1"}])])


def _structured_response() -> ModelResponse:
    return ModelResponse(result=[AIMessage(content="")], structured_response="done")


def test_returns_immediately_when_tool_call_present() -> None:
    handler_calls = []

    def handler(request):
        handler_calls.append(request)
        return _tool_call_response()

    result = retry_missing_structured_output.wrap_model_call(_model_request(), handler)

    assert len(handler_calls) == 1
    assert result.result[0].tool_calls


def test_returns_immediately_when_structured_response_present() -> None:
    handler_calls = []

    def handler(request):
        handler_calls.append(request)
        return _structured_response()

    result = retry_missing_structured_output.wrap_model_call(_model_request(), handler)

    assert len(handler_calls) == 1
    assert result.structured_response == "done"


def test_retries_once_then_succeeds_when_first_turn_has_no_tool_call() -> None:
    responses = [_no_tool_call_response(), _tool_call_response()]
    handler_calls = []

    def handler(request):
        handler_calls.append(request)
        return responses.pop(0)

    result = retry_missing_structured_output.wrap_model_call(_model_request(), handler)

    assert len(handler_calls) == 2
    assert "no tool call" in handler_calls[1].messages[-1].content.lower()
    assert result.result[0].tool_calls


def test_raises_after_exhausting_retries_with_no_tool_call() -> None:
    def handler(request):
        return _no_tool_call_response()

    with pytest.raises(StructuredOutputNotCalledError):
        retry_missing_structured_output.wrap_model_call(_model_request(), handler)
