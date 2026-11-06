"""
    Adds up the tokens and cost of the model calls made inside a block, and reports them on the block's span.
"""
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from opentelemetry import trace
from opentelemetry.trace import Span

from code_reviewer.telemetry.run_summary import TokenUsage

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class RunUsage:
    """Tokens and cost of the model calls made inside one block and inside every block nested in it.

    Output includes reasoning and input includes cached, as everywhere else, so the four never add up.
    """

    parent: "RunUsage | None"
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float = 0.0
    unpriced_calls: int = 0
    abandoned_calls: int = 0
    llm_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_tokens(self, usage: TokenUsage) -> None:
        """Counts one model call's tokens here and in every enclosing block."""
        for block in self._self_and_ancestors():
            block._add_tokens_here(usage)

    def add_cost(self, usd: float) -> None:
        """Adds one model call's cost here and in every enclosing block."""
        for block in self._self_and_ancestors():
            block._add_cost_here(usd)

    def add_unpriced_call(self) -> None:
        """Counts one model call whose model has no known price, here and in every enclosing block."""
        for block in self._self_and_ancestors():
            block._add_unpriced_call_here()

    def add_abandoned_call(self) -> None:
        """Counts one model call the caller stopped waiting for, here and in every enclosing block."""
        for block in self._self_and_ancestors():
            block._add_abandoned_call_here()

    def attributes(self) -> dict[str, int | float]:
        """The totals as span attributes, read in one step so a call finishing in another thread cannot split them."""
        with self._lock:
            return {
                "code_reviewer.tokens.input": self.input_tokens,
                "code_reviewer.tokens.output": self.output_tokens,
                "code_reviewer.tokens.reasoning": self.reasoning_tokens,
                "code_reviewer.tokens.cached": self.cached_input_tokens,
                "code_reviewer.cost_usd": self.cost_usd,
                "code_reviewer.unpriced_calls": self.unpriced_calls,
                "code_reviewer.abandoned_calls": self.abandoned_calls,
                "code_reviewer.llm_calls": self.llm_calls,
            }

    def _self_and_ancestors(self) -> Iterator["RunUsage"]:
        block: RunUsage | None = self
        while block is not None:
            yield block
            block = block.parent

    def _add_tokens_here(self, usage: TokenUsage) -> None:
        with self._lock:
            self.input_tokens += usage.input_tokens
            self.output_tokens += usage.output_tokens
            self.reasoning_tokens += usage.reasoning_tokens
            self.cached_input_tokens += usage.cached_input_tokens
            self.llm_calls += 1

    def _add_cost_here(self, usd: float) -> None:
        with self._lock:
            self.cost_usd += usd

    def _add_unpriced_call_here(self) -> None:
        with self._lock:
            self.unpriced_calls += 1

    def _add_abandoned_call_here(self) -> None:
        with self._lock:
            self.abandoned_calls += 1


_current_run: ContextVar[RunUsage | None] = ContextVar("run_usage", default=None)


@contextmanager
def track_usage(label: str) -> Iterator[RunUsage]:
    """Totals the model calls made inside the block; on exit writes them to the current span and the log.

    Yields the running total, so a caller can read it once the work inside is done.
    """
    span = trace.get_current_span()
    usage = RunUsage(parent=_current_run.get())
    token = _current_run.set(usage)
    try:
        yield usage
    finally:
        _current_run.reset(token)
        _publish(span, label, usage)


def add_tokens_to_current_run(usage: TokenUsage) -> None:
    """Counts one model call's tokens in the enclosing block; does nothing outside one."""
    _apply_to_current_run(lambda run: run.add_tokens(usage))


def add_cost_to_current_run(usd: float) -> None:
    """Adds one model call's cost to the enclosing block; does nothing outside one."""
    _apply_to_current_run(lambda run: run.add_cost(usd))


def add_unpriced_call_to_current_run() -> None:
    """Counts one call with no known price in the enclosing block; does nothing outside one."""
    _apply_to_current_run(lambda run: run.add_unpriced_call())


def add_abandoned_call_to_current_run() -> None:
    """Counts one call whose tokens are unknown because its caller timed out; does nothing outside a block."""
    _apply_to_current_run(lambda run: run.add_abandoned_call())


def _apply_to_current_run(action: Callable[[RunUsage], None]) -> None:
    """Accounting must never reach the model call it measures, so any failure is logged and dropped."""
    run = _current_run.get()
    if run is None:
        return
    try:
        action(run)
    except Exception:
        logger.warning("Could not add to the usage of the current run", exc_info=True)


def _publish(span: Span, label: str, usage: RunUsage) -> None:
    """Writes a block's totals to its span and the log; a failure here is logged and never raised."""
    try:
        attributes = usage.attributes()
        span.set_attributes(attributes)
        logger.info(
            "usage %s input=%d output=%d reasoning=%d cached=%d cost_usd=%.6f unpriced_calls=%d abandoned_calls=%d",
            label,
            attributes["code_reviewer.tokens.input"],
            attributes["code_reviewer.tokens.output"],
            attributes["code_reviewer.tokens.reasoning"],
            attributes["code_reviewer.tokens.cached"],
            attributes["code_reviewer.cost_usd"],
            attributes["code_reviewer.unpriced_calls"],
            attributes["code_reviewer.abandoned_calls"],
        )
    except Exception:
        logger.warning("Could not publish the usage of %s", label, exc_info=True)
