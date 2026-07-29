"""
    Shared exceptions for the pre-agent pipeline: raw character guard, file
    size validation, and PR file selection.
"""


class SubmissionTooLargeError(Exception):
    """Raised when submitted content exceeds the raw character cap, before any LLM call is made."""


class FileTooLargeError(Exception):
    """Raised when a file's line count exceeds the absolute cap — too large to review even split into chunks."""
