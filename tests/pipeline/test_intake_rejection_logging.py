"""
    The orchestrator drops a rejected file and reports only a reason code, so the detail of why it was
    rejected has to reach the logs. Guards are monkeypatched; nothing here calls a model.
"""
import logging

import pytest

from code_reviewer.guardrails.errors import IntakeRejectedError
from code_reviewer.pipeline import orchestrator
from code_reviewer.pipeline.errors import FileTooLargeError, SubmissionTooLargeError
from code_reviewer.schemas.submission import SubmittedFile

INTAKE_DETAIL = "Validation failed: the content reads like prose, not source code"


def _file(file_path: str, content: str = "x = 1\n") -> SubmittedFile:
    return SubmittedFile(file_path=file_path, content=content)


def _reject_content(monkeypatch: pytest.MonkeyPatch, rejected_content: str, error: Exception) -> None:
    def screen(content: str, llm=None) -> None:
        if content == rejected_content:
            raise error

    monkeypatch.setattr(orchestrator, "run_intake_screen", screen)


@pytest.fixture
def warnings_log(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.WARNING, logger=orchestrator.logger.name)
    return caplog


def test_a_rejected_source_file_is_logged_with_its_path(
    monkeypatch: pytest.MonkeyPatch, warnings_log: pytest.LogCaptureFixture
) -> None:
    """Verify that the log says which file was dropped."""
    _reject_content(monkeypatch, "bad", IntakeRejectedError(INTAKE_DETAIL))

    orchestrator.prepare_files_for_pipeline([_file("notes.py", "bad")])

    assert "file_path=notes.py" in warnings_log.text


def test_a_rejected_source_file_is_logged_with_the_reason_code_the_report_carries(
    monkeypatch: pytest.MonkeyPatch, warnings_log: pytest.LogCaptureFixture
) -> None:
    """Verify that the log and the report's skipped_files entry name the same reason."""
    _reject_content(monkeypatch, "bad", IntakeRejectedError(INTAKE_DETAIL))

    orchestrator.prepare_files_for_pipeline([_file("notes.py", "bad")])

    assert "reason=intake_rejected" in warnings_log.text


def test_a_rejected_source_file_is_logged_with_the_detail_of_why(
    monkeypatch: pytest.MonkeyPatch, warnings_log: pytest.LogCaptureFixture
) -> None:
    """Verify that the screen's own explanation, which the report drops, is in the log."""
    _reject_content(monkeypatch, "bad", IntakeRejectedError(INTAKE_DETAIL))

    orchestrator.prepare_files_for_pipeline([_file("notes.py", "bad")])

    assert INTAKE_DETAIL in warnings_log.text


def test_a_rejected_paired_test_file_is_logged_with_its_path_and_detail(
    monkeypatch: pytest.MonkeyPatch, warnings_log: pytest.LogCaptureFixture
) -> None:
    """Verify that a test file dropped from its source's pairing is logged too, not lost silently."""
    _reject_content(monkeypatch, "bad tests", IntakeRejectedError(INTAKE_DETAIL))

    orchestrator.prepare_files_for_pipeline([_file("payment.py"), _file("tests/test_payment.py", "bad tests")])

    assert ("file_path=tests/test_payment.py" in warnings_log.text, INTAKE_DETAIL in warnings_log.text) == (True, True)


def test_a_file_over_the_character_cap_is_logged_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, warnings_log: pytest.LogCaptureFixture
) -> None:
    """Verify that a size rejection is logged like an intake one, with the numbers in its message."""

    def too_long(content: str) -> None:
        raise SubmissionTooLargeError("Submission is 300000 characters, exceeding the 200000 character limit.")

    monkeypatch.setattr(orchestrator, "run_raw_character_guard", too_long)

    orchestrator.prepare_files_for_pipeline([_file("huge.py")])

    assert "reason=raw_character_limit_exceeded" in warnings_log.text


def test_a_file_over_the_line_cap_is_logged_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, warnings_log: pytest.LogCaptureFixture
) -> None:
    """Verify that the line-count rejection is logged too."""

    def too_many_lines(content: str) -> None:
        raise FileTooLargeError("File has 2000 lines, exceeding the 1500 line cap.")

    monkeypatch.setattr(orchestrator, "run_file_size_guard", too_many_lines)

    orchestrator.prepare_files_for_pipeline([_file("long.py")])

    assert "reason=file_too_large" in warnings_log.text


def test_a_file_that_passes_every_guard_logs_no_rejection(
    monkeypatch: pytest.MonkeyPatch, warnings_log: pytest.LogCaptureFixture
) -> None:
    """Verify that the rejection line appears only for files that were actually rejected."""
    monkeypatch.setattr(orchestrator, "run_intake_screen", lambda content, llm=None: None)

    orchestrator.prepare_files_for_pipeline([_file("fine.py")])

    assert "File rejected" not in warnings_log.text
