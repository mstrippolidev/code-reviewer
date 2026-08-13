"""
    ARCH dependency-direction fixture: the general depends on the
    specific. TextFormatter is a generic shared helper, but it reaches
    into the payroll-specific PayrollReport to decide how to format, so
    the reusable helper cannot be moved or reused anywhere payroll does
    not exist.
"""


class PayrollReport:
    """Application-specific report."""

    HEADER = "PAYROLL"

    def __init__(self, employee_names: list[str]) -> None:
        self.employee_names = employee_names


class TextFormatter:
    """Generic formatting helper — yet it knows what payroll is."""

    def format(self, lines: list[str]) -> str:
        return "\n".join(lines)

    def format_with_header(self, lines: list[str]) -> str:
        return f"{PayrollReport.HEADER}\n" + self.format(lines)

    def format_report(self, report: PayrollReport) -> str:
        return self.format_with_header(report.employee_names)
