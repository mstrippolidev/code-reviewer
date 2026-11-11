"""
    TEST gray-area fixture: a service that logs through a module-level logger.
    That is a module global, but it is the standard logging idiom and a test
    can capture it without changing the code.
"""
import logging

logger = logging.getLogger(__name__)


class PaymentRetry:
    def __init__(self, max_attempts: int) -> None:
        self._max_attempts = max_attempts

    def should_retry(self, attempt: int) -> bool:
        if attempt >= self._max_attempts:
            logger.warning("giving up after %d attempts", attempt)
            return False
        return True
