"""
    TCASE fixture: tests covering every path of calculate_discount.
"""
import pytest

from well_tested_source import calculate_discount


def test_negative_price_raises_value_error():
    with pytest.raises(ValueError):
        calculate_discount(-10.0, False)


def test_premium_price_gets_discount():
    assert calculate_discount(100.0, True) == 90.0


def test_non_premium_price_is_unchanged():
    assert calculate_discount(100.0, False) == 100.0
