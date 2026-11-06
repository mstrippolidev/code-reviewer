"""
    Backstop timeout independent of a provider's own SDK, which isn't
    always trustworthy to honor its own timeout kwarg. Shared by every
    caller that invokes a model directly, in or outside of AgentBase.
"""
import contextvars
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextvars import ContextVar
from typing import Callable, TypeVar

from code_reviewer.config.settings import get_settings
from code_reviewer.telemetry.run_usage import add_abandoned_call_to_current_run

_R = TypeVar("_R")

_LLM_CALL_EXECUTOR = ThreadPoolExecutor(thread_name_prefix="llm-call")

_CALL_DEADLINE: ContextVar[float | None] = ContextVar("llm_call_deadline", default=None)


class LlmDeadlineExceededError(Exception):
    """Raised in a call whose caller already gave up, so it starts no further model attempt."""


def raise_if_deadline_passed() -> None:
    """Stops an abandoned call from starting another paid model attempt."""
    deadline = _CALL_DEADLINE.get()
    if deadline is not None and time.monotonic() > deadline:
        raise LlmDeadlineExceededError("The caller stopped waiting for this LLM call.")


def call_with_hard_timeout(call: Callable[[], _R], timeout: float | None = None) -> _R:
    timeout = timeout if timeout is not None else get_settings().llm_call_timeout_seconds
    context = contextvars.copy_context()
    context.run(_CALL_DEADLINE.set, _earliest_deadline(timeout))
    future: Future[_R] = _LLM_CALL_EXECUTOR.submit(context.run, call)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as error:
        add_abandoned_call_to_current_run()
        raise TimeoutError(f"LLM call exceeded the {timeout}s hard timeout.") from error


def _earliest_deadline(timeout: float) -> float:
    """The new call's deadline, or an enclosing call's if that one ends sooner."""
    deadline = time.monotonic() + timeout
    enclosing = _CALL_DEADLINE.get()
    return deadline if enclosing is None else min(deadline, enclosing)
