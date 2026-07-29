"""
    Naming fixture: short names that are fine because their scope is small
    and obvious. VAR should NOT flag "i" or "e" here.
"""
import json


def sum_positive_values(values: list[int]) -> int:
    total = 0
    for i in range(len(values)):
        if values[i] > 0:
            total += values[i]
    return total


def parse_config(raw_config: str) -> dict:
    try:
        return json.loads(raw_config)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid config: {e}") from e
