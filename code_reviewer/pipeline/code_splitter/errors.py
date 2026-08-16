"""
    Custom errors for code split.
"""


class CodeChunkingError(Exception):
    """Raised when source code cannot be parsed as valid syntax for its
    language, or a chunk's source cannot be extracted from it."""
