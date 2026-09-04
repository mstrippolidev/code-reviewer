"""
    Backstop timeout independent of a provider's own SDK, which isn't
    always trustworthy to honor its own timeout kwarg. Shared by every
    caller that invokes a model directly, in or outside of AgentBase.
"""
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar

from code_reviewer.config.settings import get_settings

_R = TypeVar("_R")

_LLM_CALL_EXECUTOR = ThreadPoolExecutor(thread_name_prefix="llm-call")


def call_with_hard_timeout(call: Callable[[], _R]) -> _R:
    future: Future[_R] = _LLM_CALL_EXECUTOR.submit(call)
    timeout = get_settings().llm_call_timeout_seconds
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as error:
        raise TimeoutError(f"LLM call exceeded the {timeout}s hard timeout.") from error
