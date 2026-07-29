import pytest

from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline.errors import SubmissionTooLargeError
from code_reviewer.pipeline.raw_character_guard import run_raw_character_guard


@pytest.fixture(autouse=True)
def small_character_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_submission_characters", 10)


def test_content_within_cap_does_not_raise() -> None:
    run_raw_character_guard("short")


def test_content_at_exact_cap_does_not_raise() -> None:
    run_raw_character_guard("a" * 10)


def test_content_over_cap_raises() -> None:
    with pytest.raises(SubmissionTooLargeError):
        run_raw_character_guard("a" * 11)


def test_error_message_reports_actual_and_max_length() -> None:
    with pytest.raises(SubmissionTooLargeError, match="11 characters.*10 character limit"):
        run_raw_character_guard("a" * 11)
