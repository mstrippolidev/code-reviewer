"""
    Tests for dedupe_tool_calls: short-circuits a tool call that exactly
    repeats one already in the conversation, without re-executing it. No
    LLM involved — pure logic against a hand-built ToolCallRequest.
"""
from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import AIMessage

from code_reviewer.agents.llm.middleware import _already_called, dedupe_tool_calls

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
