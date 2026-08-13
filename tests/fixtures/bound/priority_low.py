"""
    BOUND priority=low fixture: TemperatureReading exposes one small
    conversion helper as public that is only ever used internally, but
    nothing external actually calls it and the class is otherwise tightly
    scoped — a minor lapse rather than a genuinely wide surface.
"""


class TemperatureReading:
    def __init__(self, celsius: float) -> None:
        self.celsius = celsius

    def to_fahrenheit(self) -> float:
        return self.celsius_to_fahrenheit(self.celsius)

    def celsius_to_fahrenheit(self, celsius: float) -> float:
        return (celsius * 9 / 5) + 32
