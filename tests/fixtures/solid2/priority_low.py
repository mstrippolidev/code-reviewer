"""
    SOLID2 priority=low fixture: a concrete dependency on the filesystem,
    but confined to a tiny debug-only helper with limited reach.
"""


class _DebugLogger:
    """Debug-only helper, never used from a production code path."""

    def log(self, message: str) -> None:
        with open("/tmp/debug.log", "a") as debug_file:
            debug_file.write(message + "\n")
