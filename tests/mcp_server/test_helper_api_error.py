import httpx
import pytest

from mcp_server.tools.helper_api_error import UNREADABLE_DETAIL, detail_of, retry_after_hint, validation_errors_of


@pytest.mark.parametrize(
    "response,expected_detail",
    [
        (httpx.Response(400, json={"detail": "Branch 'mian' was not found"}), "Branch 'mian' was not found"),
        (httpx.Response(400, json={"detail": "Repo is too small."}), "Repo is too small"),
        (httpx.Response(400, json={"detail": ["not", "a", "string"]}), UNREADABLE_DETAIL),
        (httpx.Response(400, json={"other": "no detail key"}), UNREADABLE_DETAIL),
        (httpx.Response(400, json=["not an object"]), UNREADABLE_DETAIL),
        (httpx.Response(400, text="<html>bad</html>"), UNREADABLE_DETAIL),
    ],
)
def test_detail_of_reads_the_api_detail_or_falls_back(response: httpx.Response, expected_detail: str) -> None:
    """Verify that a refusal's detail is used when it is readable text and replaced by a stock phrase otherwise."""
    assert detail_of(response) == expected_detail


def _validation_response(*errors: dict) -> httpx.Response:
    return httpx.Response(422, json={"detail": list(errors)})


def test_validation_errors_of_names_the_field_and_the_message() -> None:
    """Verify that the LLM is told which argument was wrong and why, including any list of valid values."""
    response = _validation_response({"loc": ["body", "agents", 0], "msg": "Input should be 'SOLID1' or 'VAR'"})

    assert validation_errors_of(response) == "agents: Input should be 'SOLID1' or 'VAR'"


def test_validation_errors_of_drops_pydantics_value_error_prefix() -> None:
    """Verify that a rule written as a validator reads as the rule itself, not as a Python error."""
    response = _validation_response({"loc": ["body", "agents"], "msg": "Value error, DRY needs a registered repo"})

    assert validation_errors_of(response) == "agents: DRY needs a registered repo"


def test_validation_errors_of_joins_several_errors() -> None:
    """Verify that one request with two bad arguments reports both."""
    response = _validation_response(
        {"loc": ["body", "agents"], "msg": "List should have at least 1 item"},
        {"loc": ["body", "file_paths"], "msg": "List should have at most 15 items"},
    )

    assert validation_errors_of(response) == (
        "agents: List should have at least 1 item; file_paths: List should have at most 15 items"
    )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(422, json={"detail": []}),
        httpx.Response(422, json={"detail": None}),
        httpx.Response(422, json={"detail": "plain text"}),
        httpx.Response(422, json={"detail": [{"msg": "no location"}]}),
        httpx.Response(422, json={"detail": [{"loc": ["body"], "msg": "short location"}]}),
        httpx.Response(422, text="<html>bad</html>"),
    ],
)
def test_validation_errors_of_falls_back_when_the_shape_is_unexpected(response: httpx.Response) -> None:
    """Verify that a 422 body that is not FastAPI's error list never crashes the error path."""
    assert validation_errors_of(response) == UNREADABLE_DETAIL


def test_retry_after_hint_states_how_long_to_wait() -> None:
    """Verify that the Retry-After header becomes a sentence the LLM can act on."""
    response = httpx.Response(429, headers={"Retry-After": "30"})

    assert retry_after_hint(response) == " Retry after 30 seconds."


def test_retry_after_hint_is_empty_when_api_gave_no_wait_time() -> None:
    """Verify that no header leaves nothing to append, instead of inventing a wait time."""
    assert retry_after_hint(httpx.Response(429)) == ""
