from priority_high_source import calculate_shipping_cost


def test_light_package_costs_flat_rate():
    assert calculate_shipping_cost(0.5) == 5.0
