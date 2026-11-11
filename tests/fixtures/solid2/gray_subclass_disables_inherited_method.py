"""
    SOLID2 gray-area fixture: a read-only subclass that disables one
    inherited method by raising. It narrows the parent's contract, but the
    method is optional in practice, so how serious it is is a judgment call.
"""


class ReportStore:
    def load(self, report_id: str) -> str:
        return f"report {report_id}"

    def archive(self, report_id: str) -> None:
        print(f"archiving {report_id}")


class ReadOnlyReportStore(ReportStore):
    def archive(self, report_id: str) -> None:
        raise NotImplementedError("a read-only store cannot archive reports")


def archive_old_reports(store: ReportStore, report_ids: list[str]) -> None:
    for report_id in report_ids:
        store.archive(report_id)
