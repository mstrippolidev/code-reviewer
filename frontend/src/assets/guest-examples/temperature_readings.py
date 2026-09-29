from dataclasses import dataclass
from statistics import mean


class EmptyReadingsError(Exception):
    """Raised when a summary is requested for a sensor with no readings."""


@dataclass(frozen=True)
class Reading:
    sensor_id: str
    celsius: float


@dataclass(frozen=True)
class SensorSummary:
    sensor_id: str
    average_celsius: float
    peak_celsius: float


def summarize_sensor(sensor_id: str, readings: list[Reading]) -> SensorSummary:
    sensor_readings = [reading.celsius for reading in readings if reading.sensor_id == sensor_id]
    if not sensor_readings:
        raise EmptyReadingsError(f"No readings recorded for sensor {sensor_id}")
    return SensorSummary(
        sensor_id=sensor_id,
        average_celsius=mean(sensor_readings),
        peak_celsius=max(sensor_readings),
    )


def to_fahrenheit(celsius: float) -> float:
    return celsius * 9 / 5 + 32
