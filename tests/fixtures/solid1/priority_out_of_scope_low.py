"""
    SOLID1 out-of-scope fixture: temporal coupling — generate() silently
    produces garbage if configure() wasn't called first, since nothing
    enforces the required call order. This is SRP/OCP-adjacent (the class
    has an implicit, unenforced second responsibility: its own setup
    order) but is not itself an unrelated-responsibilities bundle, an OCP
    violation, a multi-thing function, a param-count issue, or a boolean
    flag argument — a real finding outside the five in-scope categories.
"""


class ReportGenerator:
    def __init__(self) -> None:
        self._configured = False
        self._data = None

    def configure(self, data: list) -> None:
        self._data = data
        self._configured = True

    def generate(self) -> str:
        return f"Report with {len(self._data)} rows"
