class _FoundNegative(Exception):
    def __init__(self, value: int) -> None:
        self.value = value


def find_first_negative(numbers: list[int]) -> int:
    try:
        for number in numbers:
            if number < 0:
                raise _FoundNegative(number)
        return -1
    except _FoundNegative as found:
        return found.value
