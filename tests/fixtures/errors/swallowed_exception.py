"""
    Error handling fixture: a bare except silently swallows the failure
    instead of handling it or letting it propagate.
"""
import json


def load_config(path: str) -> dict:
    try:
        with open(path) as config_file:
            return json.load(config_file)
    except Exception:
        pass
