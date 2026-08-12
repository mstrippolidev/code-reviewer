"""
    COUP priority=medium fixture: feature envy. Every line of
    TimesheetSummarizer.summarize reads Timesheet's data and none of it
    touches the summarizer's own state, so the logic belongs on Timesheet.
"""


class Timesheet:
    def __init__(self, employee: str, hours_by_day: dict[str, float]) -> None:
        self.employee = employee
        self.hours_by_day = hours_by_day
        self.hourly_rate = 25.0


class TimesheetSummarizer:
    def __init__(self, currency_symbol: str) -> None:
        self._currency_symbol = currency_symbol

    def summarize(self, timesheet: Timesheet) -> str:
        total_hours = sum(timesheet.hours_by_day.values())
        pay = total_hours * timesheet.hourly_rate
        return f"{timesheet.employee}: {total_hours}h = {self._currency_symbol}{pay}"
