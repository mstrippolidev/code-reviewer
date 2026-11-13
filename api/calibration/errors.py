class CalibrationPairNotFoundError(Exception):
    """Raised when no pair has the requested pair id."""


class NoUnlabeledPairError(Exception):
    """Raised when the caller has labeled every pair."""
