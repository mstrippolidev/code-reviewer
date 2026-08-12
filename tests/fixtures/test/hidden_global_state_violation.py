"""
    TEST violation fixture: hidden global state. increment_session_count
    and reset_session_count both mutate a module-level global, so tests
    for either function depend on execution order and cannot start from a
    clean, isolated state.
"""

_active_sessions = 0


def increment_session_count() -> int:
    global _active_sessions
    _active_sessions += 1
    return _active_sessions


def reset_session_count() -> None:
    global _active_sessions
    _active_sessions = 0
