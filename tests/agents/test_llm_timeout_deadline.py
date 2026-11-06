"""
    Tests for the deadline that call_with_hard_timeout leaves behind: an abandoned call keeps running
    in its worker thread, so it must refuse to start another model attempt once its caller gave up.
"""
import threading

import pytest

from code_reviewer.agents.llm.timeout import (
    LlmDeadlineExceededError,
    call_with_hard_timeout,
    raise_if_deadline_passed,
)
from code_reviewer.telemetry.run_usage import track_usage

_SHORT_TIMEOUT_SECONDS = 0.05
_WAIT_FOR_THREAD_SECONDS = 5


def test_a_call_inside_its_deadline_may_start_another_attempt() -> None:
    """Verify the check passes while the caller is still waiting."""
    call_with_hard_timeout(raise_if_deadline_passed, timeout=5)


def test_a_call_outside_any_hard_timeout_has_no_deadline() -> None:
    """Verify code that never went through call_with_hard_timeout is not stopped."""
    raise_if_deadline_passed()


def test_an_abandoned_call_is_refused_another_attempt() -> None:
    """Verify the worker thread of a timed-out call raises instead of starting a new paid attempt."""
    release = threading.Event()
    finished = threading.Event()
    outcome: list[BaseException | None] = []

    def slow_call_that_retries() -> None:
        release.wait(_WAIT_FOR_THREAD_SECONDS)
        try:
            raise_if_deadline_passed()
            outcome.append(None)
        except LlmDeadlineExceededError as error:
            outcome.append(error)
        finished.set()

    with pytest.raises(TimeoutError):
        call_with_hard_timeout(slow_call_that_retries, timeout=_SHORT_TIMEOUT_SECONDS)
    release.set()
    finished.wait(_WAIT_FOR_THREAD_SECONDS)

    assert isinstance(outcome[0], LlmDeadlineExceededError)


def test_a_timed_out_call_is_counted_as_abandoned_in_the_enclosing_block() -> None:
    """Verify the block knows a call it paid for reported no tokens, so its totals read as a lower bound."""
    release = threading.Event()

    with track_usage("agent=DRY") as total:
        with pytest.raises(TimeoutError):
            call_with_hard_timeout(lambda: release.wait(_WAIT_FOR_THREAD_SECONDS), timeout=_SHORT_TIMEOUT_SECONDS)
    release.set()

    assert total.abandoned_calls == 1


def test_an_inner_call_cannot_outlive_the_call_around_it() -> None:
    """Verify a nested hard timeout keeps the enclosing call's earlier deadline."""
    release = threading.Event()
    outcome: list[BaseException | None] = []
    finished = threading.Event()

    def inner_call() -> None:
        release.wait(_WAIT_FOR_THREAD_SECONDS)
        try:
            raise_if_deadline_passed()
            outcome.append(None)
        except LlmDeadlineExceededError as error:
            outcome.append(error)
        finished.set()

    def outer_call() -> None:
        call_with_hard_timeout(inner_call, timeout=60)

    with pytest.raises(TimeoutError):
        call_with_hard_timeout(outer_call, timeout=_SHORT_TIMEOUT_SECONDS)
    release.set()
    finished.wait(_WAIT_FOR_THREAD_SECONDS)

    assert isinstance(outcome[0], LlmDeadlineExceededError)
