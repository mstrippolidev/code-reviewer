from httpx import Response

RETRY_AFTER_HEADER = "Retry-After"
UNREADABLE_DETAIL = "api/ refused the request"
VALUE_ERROR_PREFIX = "Value error, "


def detail_of(response: Response) -> str:
    """The `detail` api/ gave for a refusal, without a trailing full stop; a stock phrase when it gave none."""
    try:
        detail = response.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return UNREADABLE_DETAIL
    return detail.rstrip(".") if isinstance(detail, str) else UNREADABLE_DETAIL


def validation_errors_of(response: Response) -> str:
    """The per-field messages of a 422, such as "agents: Input should be 'SOLID1', ...", joined into one sentence."""
    try:
        errors = response.json()["detail"]
        messages = (f"{error['loc'][1]}: {error['msg'].removeprefix(VALUE_ERROR_PREFIX)}" for error in errors)
        return "; ".join(messages) or UNREADABLE_DETAIL
    except (ValueError, KeyError, TypeError, IndexError):
        return UNREADABLE_DETAIL


def retry_after_hint(response: Response) -> str:
    """A ready-to-append sentence telling the LLM how long to wait, or an empty string when api/ gave no wait time."""
    retry_after = response.headers.get(RETRY_AFTER_HEADER)
    return f" Retry after {retry_after} seconds." if retry_after else ""
