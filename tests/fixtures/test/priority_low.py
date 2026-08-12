"""
    TEST priority=low fixture: one constructor dependency more than the
    class obviously needs. NotificationPreferences only ever uses
    _logger for a single debug line, so it's a minor excess, not a real
    barrier to testing this class in isolation.
"""


class Logger:
    def debug(self, message: str) -> None:
        print(message)


class NotificationPreferences:
    def __init__(self, email_opt_in: bool, logger: Logger) -> None:
        self._email_opt_in = email_opt_in
        self._logger = logger

    def is_enabled(self) -> bool:
        self._logger.debug("checked notification preference")
        return self._email_opt_in
