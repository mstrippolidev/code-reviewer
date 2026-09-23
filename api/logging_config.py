"""
    Without this, Python's default logging handler only ever surfaces WARNING and above.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from api.config.settings import ApiSettings

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_FILE = Path("logs") / "api.log"
_LOG_FILE_MAX_BYTES = 5_000_000
_LOG_FILE_BACKUP_COUNT = 3


def configure_logging(settings: ApiSettings) -> None:
    """force=True is required here, not optional: libraries loaded during
    lifespan startup (sentence-transformers/huggingface_hub, pulled in by
    the cross-encoder reranker) attach their own root handler as a side
    effect of loading, which makes a plain basicConfig() a silent no-op —
    every subsequent log call falls back to Python's default WARNING-level,
    unformatted, file-less config with no error to signal it."""
    _LOG_FILE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=settings.api_log_level,
        format=_LOG_FORMAT,
        handlers=[logging.StreamHandler(), _build_file_handler()],
        force=True,
    )


def _build_file_handler() -> logging.Handler:
    handler = RotatingFileHandler(_LOG_FILE, maxBytes=_LOG_FILE_MAX_BYTES, backupCount=_LOG_FILE_BACKUP_COUNT)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    return handler
