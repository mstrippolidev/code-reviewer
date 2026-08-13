"""
    ARCH priority=medium fixture: construction assembled inside the logic
    that uses it. ExportJob builds its own CsvWriter partway through
    run(), reading a config value to decide the delimiter, instead of
    receiving an already-built writer from its caller.
"""
import os


class CsvWriter:
    def __init__(self, delimiter: str) -> None:
        self._delimiter = delimiter

    def write(self, rows: list[list[str]]) -> str:
        return "\n".join(self._delimiter.join(row) for row in rows)


class ExportJob:
    def run(self, rows: list[list[str]]) -> str:
        prepared = [[cell.strip() for cell in row] for row in rows]
        delimiter = os.environ.get("EXPORT_DELIMITER", ",")
        writer = CsvWriter(delimiter)
        return writer.write(prepared)
