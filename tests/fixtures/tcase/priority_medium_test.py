from priority_medium_source import RequestCounter


def test_increment_increases_total():
    counter = RequestCounter()
    counter.increment()
    counter.increment()
    assert counter.total() == 2
