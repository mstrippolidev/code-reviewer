"""
    TCASE fixture: tests covering only the empty-list and single-item paths.
"""
from partially_tested_source import calculate_total


def test_empty_list_returns_zero():
    assert calculate_total([]) == 0.0


def test_single_item_returns_that_amount():
    assert calculate_total([10.0]) == 10.0
