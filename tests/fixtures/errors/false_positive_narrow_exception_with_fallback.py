"""
    ERR false-positive fixture: catches one specific, expected exception
    type and returns a well-defined fallback. Should NOT be flagged as a
    swallowed exception — item 4 targets a bare except or one that only
    logs and continues; this one names the exact failure and responds to
    it deliberately.
"""


def load_config(path: str) -> dict[str, str]:
    try:
        with open(path) as config_file:
            return dict(line.strip().split("=", 1) for line in config_file)
    except FileNotFoundError:
        return {"log_level": "info"}
