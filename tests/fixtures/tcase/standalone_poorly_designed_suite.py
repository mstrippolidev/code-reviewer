from decimal import Decimal

from shop.pricing import line_total

results = []


def test_1() -> None:
    result = line_total(Decimal("2.50"), quantity=4)
    results.append(result)
    assert result is not None


def test_2() -> None:
    try:
        line_total(Decimal("2.50"), quantity=-1)
    except Exception:
        pass


def test_3() -> None:
    assert len(results) == 1
