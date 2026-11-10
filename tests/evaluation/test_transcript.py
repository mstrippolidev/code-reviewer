"""
    Tests for turning agent messages into a stored transcript: hand-built messages, no model.
"""
import threading

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from code_reviewer.telemetry.run_transcript import capture_transcript, record_transcript
from evaluation.transcript import transcript_of


def test_reasoning_stored_by_langchain_openrouter_is_read() -> None:
    """Verify reasoning_content in additional_kwargs becomes the message's reasoning."""
    message = AIMessage(content="answer", additional_kwargs={"reasoning_content": "weighing the options"})

    transcript = transcript_of([message])

    assert transcript.messages[0].reasoning == "weighing the options"
    assert transcript.has_reasoning


def test_reasoning_content_blocks_are_read_when_nothing_is_stored_beside_the_content() -> None:
    """Verify a thinking block in the content list is the reasoning and the text block is the text."""
    message = AIMessage(
        content=[{"type": "thinking", "thinking": "step one"}, {"type": "text", "text": "final words"}]
    )

    entry = transcript_of([message]).messages[0]

    assert entry.reasoning == "step one"
    assert entry.text == "final words"


def test_a_message_without_reasoning_says_so() -> None:
    """Verify a transcript with no reasoning anywhere reports has_reasoning False."""
    transcript = transcript_of([HumanMessage(content="code"), AIMessage(content="answer")])

    assert transcript.messages[1].reasoning is None
    assert not transcript.has_reasoning


def test_saved_json_keeps_the_reasoning_length_but_not_its_text() -> None:
    """Verify a serialized transcript carries how much reasoning there was, never the reasoning itself."""
    message = AIMessage(content="answer", additional_kwargs={"reasoning_content": "weighing the options"})

    saved = transcript_of([message]).model_dump_json()

    assert "weighing the options" not in saved
    assert '"reasoning_characters":20' in saved
    assert '"has_reasoning":true' in saved


def test_reply_details_sent_by_the_provider_are_kept() -> None:
    """Verify the model and finish details in an assistant reply's response_metadata are recorded, and nothing else."""
    message = AIMessage(
        content="answer",
        response_metadata={"model_name": "model-x", "native_finish_reason": "stop", "cost": 0.01},
    )

    entry = transcript_of([message]).messages[0]

    assert entry.reply_details == {"model_name": "model-x", "native_finish_reason": "stop"}


def test_roles_and_order_are_kept() -> None:
    """Verify user, assistant and tool messages keep their order and plain role names."""
    messages = [HumanMessage(content="code"), AIMessage(content="a"), ToolMessage(content="r", tool_call_id="1")]

    roles = [entry.role for entry in transcript_of(messages).messages]

    assert roles == ["user", "assistant", "tool"]


def test_tool_calls_and_tool_results_keep_their_names() -> None:
    """Verify an assistant tool call and the tool's reply both name the tool."""
    call = AIMessage(content="", tool_calls=[{"name": "get_file_chunks", "args": {"file_path": "a.py"}, "id": "1"}])
    reply = ToolMessage(content="chunks", tool_call_id="1", name="get_file_chunks")

    entries = transcript_of([call, reply]).messages

    assert entries[0].tool_calls[0].name == "get_file_chunks"
    assert entries[0].tool_calls[0].arguments == {"file_path": "a.py"}
    assert entries[1].tool_name == "get_file_chunks"


def test_recording_with_no_open_capture_does_nothing() -> None:
    """Verify record_transcript outside a capture block neither raises nor leaks into the next capture."""
    record_transcript([AIMessage(content="early")])

    with capture_transcript() as captured:
        record_transcript([AIMessage(content="inside")])

    assert [message.content for message in captured] == ["inside"]


def test_captures_in_two_threads_do_not_mix() -> None:
    """Verify each thread's capture holds only the messages recorded in that thread."""
    captured_by_thread: dict[str, list[str]] = {}

    def run(name: str) -> None:
        with capture_transcript() as captured:
            record_transcript([AIMessage(content=name)])
        captured_by_thread[name] = [str(message.content) for message in captured]

    threads = [threading.Thread(target=run, args=(name,)) for name in ("first", "second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert captured_by_thread == {"first": ["first"], "second": ["second"]}
