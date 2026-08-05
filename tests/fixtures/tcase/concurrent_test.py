"""
    TCASE fixture: only sequential coverage of RequestCounter, despite it
    being documented as used from concurrent contexts.
"""
from concurrent_source import RequestCounter


def test_increment_increases_count_by_one():
    counter = RequestCounter()
    counter.increment()
    assert counter.current_count() == 1


def test_multiple_sequential_increments():
    counter = RequestCounter()
    counter.increment()
    counter.increment()
    counter.increment()
    assert counter.current_count() == 3
