import pytest

from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline.errors import FileTooLargeError
from code_reviewer.pipeline.file_size import run_file_size_guard
from code_reviewer.schemas.review import SizeStatus


def _content_with_lines(line_count: int) -> str:
    """Builds content with exactly line_count newline characters."""
    return "x\n" * line_count


@pytest.fixture(autouse=True)
def bounded_max_file_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_file_lines", 900)


def test_under_soft_limit_is_normal() -> None:
    assert run_file_size_guard(_content_with_lines(499)) == SizeStatus.NORMAL


def test_at_soft_limit_boundary_is_soft_limit() -> None:
    assert run_file_size_guard(_content_with_lines(500)) == SizeStatus.SOFT_LIMIT


def test_at_hard_limit_boundary_is_soft_limit() -> None:
    assert run_file_size_guard(_content_with_lines(750)) == SizeStatus.SOFT_LIMIT


def test_just_over_hard_limit_is_hard_limit_exceeded() -> None:
    assert run_file_size_guard(_content_with_lines(751)) == SizeStatus.HARD_LIMIT_EXCEEDED


def test_at_max_file_lines_boundary_does_not_raise() -> None:
    assert run_file_size_guard(_content_with_lines(900)) == SizeStatus.HARD_LIMIT_EXCEEDED


def test_over_max_file_lines_raises() -> None:
    with pytest.raises(FileTooLargeError):
        run_file_size_guard(_content_with_lines(901))
