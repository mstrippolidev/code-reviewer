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
    _LOG_FILE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=settings.api_log_level,
        format=_LOG_FORMAT,
        handlers=[logging.StreamHandler(), _build_file_handler()],
    )


def _build_file_handler() -> logging.Handler:
    handler = RotatingFileHandler(_LOG_FILE, maxBytes=_LOG_FILE_MAX_BYTES, backupCount=_LOG_FILE_BACKUP_COUNT)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    return handler
