from decimal import Decimal

import pytest

from shop.pricing import InvalidQuantityError, line_total


def test_line_total_multiplies_unit_price_by_quantity() -> None:
    assert line_total(Decimal("2.50"), quantity=4) == Decimal("10.00")


def test_line_total_of_zero_quantity_is_zero() -> None:
    assert line_total(Decimal("2.50"), quantity=0) == Decimal("0.00")


def test_line_total_rounds_half_up_to_cents() -> None:
    assert line_total(Decimal("0.125"), quantity=1) == Decimal("0.13")


def test_line_total_with_negative_quantity_raises_invalid_quantity_error() -> None:
    with pytest.raises(InvalidQuantityError):
        line_total(Decimal("2.50"), quantity=-1)
