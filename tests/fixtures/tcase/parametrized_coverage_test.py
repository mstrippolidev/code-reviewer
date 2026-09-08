"""
    TCASE fixture: one parametrized test covering all three branches of
    shipping_cost.
"""
import pytest

from parametrized_coverage_source import shipping_cost


@pytest.mark.parametrize(
    "weight_kg,expected_cost",
    [
        (-1.0, 5.0),
        (0.0, 5.0),
        (0.5, 5.0),
        (1.0, 5.0),
        (3.0, 10.0),
        (5.0, 10.0),
        (5.5, 20.0),
        (10.0, 20.0),
    ],
)
def test_shipping_cost_by_weight_tier(weight_kg: float, expected_cost: float) -> None:
    assert shipping_cost(weight_kg) == expected_cost
