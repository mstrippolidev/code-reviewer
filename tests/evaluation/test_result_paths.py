"""
    Tests for where an evaluation run's files are put: pure path building, nothing written.
"""
from datetime import datetime, timezone
from pathlib import Path

from evaluation.result_paths import folder_name_of, result_files

RESULTS = Path("results")
MOMENT = datetime(2026, 11, 10, 1, 38, 34, tzinfo=timezone.utc)


def test_scores_and_transcripts_go_in_the_models_day_folder() -> None:
    """Verify each model gets a folder and each day a folder inside it."""
    files = result_files(RESULTS, "deepseek/deepseek-v4-pro-0813", MOMENT, "bound")

    day_folder = RESULTS / "deepseek__deepseek-v4-pro-0813" / "2026-11-10"
    assert files.scores == day_folder / "20261110-013834-bound.json"
    assert files.transcripts == day_folder / "20261110-013834-bound-transcripts.md"


def test_the_reasoning_log_goes_in_the_models_logs_folder() -> None:
    """Verify reasoning is kept apart from the day folders, so the readable files never sit beside it."""
    files = result_files(RESULTS, "deepseek/deepseek-v4-pro-0813", MOMENT, "bound")

    assert files.reasoning_log == RESULTS / "deepseek__deepseek-v4-pro-0813" / "logs" / "20261110-013834-bound-reasoning.log"


def test_a_model_id_with_a_colon_is_a_safe_folder_name() -> None:
    """Verify ids such as `vendor/model:free` do not create nested folders or odd characters."""
    assert folder_name_of("vendor/model:free") == "vendor__model_free"
