"""
    Business ids and the trace id stamped on every log line of the current work.
"""
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from opentelemetry import trace
from pydantic import BaseModel


class CorrelationIds(BaseModel, frozen=True):
    """The ids that name one unit of work; unset ones are left out of the log line."""

    review_id: UUID | None = None
    search_id: UUID | None = None
    repo_id: int | None = None
    owner_id: int | None = None


_current_ids: ContextVar[CorrelationIds] = ContextVar("correlation_ids", default=CorrelationIds())


@contextmanager
def correlation_scope(ids: CorrelationIds) -> Iterator[None]:
    """Stamps the ids on every log line emitted inside the block, then restores the previous ones."""
    token = _current_ids.set(ids)
    try:
        yield
    finally:
        _current_ids.reset(token)


class CorrelationFilter(logging.Filter):
    """Adds trace_id and correlation fields to every record so the log format can always print them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _current_trace_id()
        record.correlation = _render(_current_ids.get())
        return True


def _current_trace_id() -> str:
    """The active span's trace id as 32 hex characters, or '-' when there is none."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else "-"


def _render(ids: CorrelationIds) -> str:
    """Renders the set ids as space-separated key=value pairs."""
    return " ".join(f"{name}={value}" for name, value in ids.model_dump(exclude_none=True).items())
