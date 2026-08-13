"""
    ARCH false-positive fixture: a general base class defining a fixed
    algorithm skeleton and calling an abstract step its subclasses
    override. Should NOT be flagged as a wrong-direction dependency — the
    base class depends only on its own abstract method, never on a named
    subclass, so it stays reusable and the direction points correctly
    from specific to general.
"""
from abc import ABC, abstractmethod


class ReportExporter(ABC):
    def export(self, rows: list[str]) -> str:
        header = self._header()
        body = "\n".join(rows)
        return f"{header}\n{body}"

    @abstractmethod
    def _header(self) -> str: ...


class CsvReportExporter(ReportExporter):
    def _header(self) -> str:
        return "id,total"
