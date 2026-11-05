from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from code_reviewer.telemetry.run_summary import RunSummary, summarize_run


def _ai_message(input_tokens: int, output_tokens: int, reasoning: int = 0, cache_read: int = 0) -> AIMessage:
    """An AIMessage carrying the usage metadata a provider reports for one model turn."""
    return AIMessage(
        content="",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": {"cache_read": cache_read},
            "output_token_details": {"reasoning": reasoning},
        },
    )


def _tool_message(name: str | None, status: str) -> ToolMessage:
    """A ToolMessage as a finished tool call leaves it in the agent's history."""
    return ToolMessage(content="result", tool_call_id="call-1", name=name, status=status)


def test_summarize_run_with_no_messages_returns_an_empty_summary() -> None:
    """Verify a run that left no messages reports zeros instead of failing."""
    assert summarize_run([]) == RunSummary()


def test_summarize_run_adds_input_tokens_across_model_turns() -> None:
    """Verify a multi-turn run, such as a tool round-trip, counts the input tokens of every turn."""
    messages = [_ai_message(100, 10), _ai_message(150, 20)]

    summary = summarize_run(messages)

    assert summary.input_tokens == 250


def test_summarize_run_adds_output_tokens_across_model_turns() -> None:
    """Verify output tokens are totalled across turns the same way input tokens are."""
    messages = [_ai_message(100, 10), _ai_message(150, 20)]

    summary = summarize_run(messages)

    assert summary.output_tokens == 30


def test_summarize_run_reads_reasoning_tokens_from_the_output_details() -> None:
    """Verify reasoning tokens come from output_token_details, where a reasoning model reports them."""
    messages = [_ai_message(100, 80, reasoning=60)]

    summary = summarize_run(messages)

    assert summary.reasoning_tokens == 60


def test_summarize_run_reads_cached_tokens_from_the_input_details() -> None:
    """Verify cached input tokens come from input_token_details.cache_read."""
    messages = [_ai_message(100, 10, cache_read=40)]

    summary = summarize_run(messages)

    assert summary.cached_input_tokens == 40


def test_summarize_run_counts_one_model_turn_per_ai_message() -> None:
    """Verify model turns count AI messages only, so a looping agent shows a high number."""
    messages = [HumanMessage(content="code"), _ai_message(10, 5), _tool_message("lookup", "success"), _ai_message(10, 5)]

    summary = summarize_run(messages)

    assert summary.model_turns == 2


def test_summarize_run_counts_an_ai_message_without_usage_as_a_turn_with_zero_tokens() -> None:
    """Verify a provider that reports no usage still counts the turn but adds no tokens."""
    messages = [AIMessage(content="no usage reported")]

    summary = summarize_run(messages)

    assert (summary.model_turns, summary.input_tokens) == (1, 0)


def test_summarize_run_records_a_successful_tool_call_as_not_failed() -> None:
    """Verify a tool message with status success is reported as a call that did not fail."""
    summary = summarize_run([_tool_message("get_file_chunks", "success")])

    assert summary.tool_calls[0].failed is False


def test_summarize_run_records_an_errored_tool_call_as_failed() -> None:
    """Verify a tool message with status error is reported as a failed call, so tool failure rate can be charted."""
    summary = summarize_run([_tool_message("get_file_chunks", "error")])

    assert summary.tool_calls[0].failed is True


def test_summarize_run_names_a_tool_call_after_the_tool() -> None:
    """Verify the tool name is kept, so calls can be split per tool."""
    summary = summarize_run([_tool_message("get_file_chunks", "success")])

    assert summary.tool_calls[0].name == "get_file_chunks"


def test_summarize_run_names_an_unnamed_tool_call_unknown() -> None:
    """Verify a tool message without a name still produces a record with a stable label."""
    summary = summarize_run([_tool_message(None, "success")])

    assert summary.tool_calls[0].name == "unknown"
