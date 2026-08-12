from priority_low_source import clamp_to_positive


def test_positive_value_is_unchanged():
    assert clamp_to_positive(5) == 5
