"""
    Where one agent's evaluation files go: a folder per model, a folder per day inside it for the
    scores and transcripts, and a logs folder beside the days for the model's reasoning.
"""
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

LOGS_FOLDER = "logs"
REASONING_LOG_SUFFIX = "-reasoning.log"


class ResultFiles(BaseModel):
    scores: Path
    transcripts: Path
    reasoning_log: Path


def result_files(results_dir: Path, model: str, created_at: datetime, agent: str) -> ResultFiles:
    """The three paths for one agent's run of `model`; nothing is created on disk."""
    model_dir = results_dir / folder_name_of(model)
    stem = f"{created_at:%Y%m%d-%H%M%S}-{agent}"
    return ResultFiles(
        scores=model_dir / f"{created_at:%Y-%m-%d}" / f"{stem}.json",
        transcripts=model_dir / f"{created_at:%Y-%m-%d}" / f"{stem}-transcripts.md",
        reasoning_log=model_dir / LOGS_FOLDER / f"{stem}{REASONING_LOG_SUFFIX}",
    )


def folder_name_of(model: str) -> str:
    """A model id such as `deepseek/deepseek-v4-pro-0813` as one folder name."""
    return model.replace("/", "__").replace(":", "_")
