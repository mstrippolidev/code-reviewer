def checkout_total(price: float) -> float:
    return _stage_1(price)


def _stage_1(price: float) -> float:
    return _stage_2(price)


def _stage_2(price: float) -> float:
    return _stage_3(price)


def _stage_3(price: float) -> float:
    return _stage_4(price)


def _stage_4(price: float) -> float:
    return _stage_5(price)


def _stage_5(price: float) -> float:
    return _stage_6(price)


def _stage_6(price: float) -> float:
    return _stage_7(price)


def _stage_7(price: float) -> float:
    return _stage_8(price)


def _stage_8(price: float) -> float:
    return _stage_9(price)


def _stage_9(price: float) -> float:
    return _stage_10(price)


def _stage_10(price: float) -> float:
    if price > 100:
        return price * 0.9
    return price
