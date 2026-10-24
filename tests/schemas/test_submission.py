import pytest
from pydantic import ValidationError

from code_reviewer.pipeline.call_depth.depth_follower import CallDepth, DepthReport, WalkEnd
from code_reviewer.schemas.review import SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile


def test_submitted_file_accepts_path_and_content() -> None:
    file = SubmittedFile(file_path="app/service.py", content="print('hi')\n")

    assert file.file_path == "app/service.py"
    assert file.content == "print('hi')\n"


def test_submitted_file_requires_both_fields() -> None:
    with pytest.raises(ValidationError):
        SubmittedFile(file_path="app/service.py")


def _prepared_file(**fields: object) -> PreparedFile:
    source = SubmittedFile(file_path="app/service.py", content="x = 1\n")
    return PreparedFile(source_file=source, size_status=SizeStatus.NORMAL, **fields)


def test_prepared_file_has_no_call_depth_reports_by_default() -> None:
    assert _prepared_file().call_depth_reports == []


def test_prepared_file_carries_the_call_depth_reports_it_is_given() -> None:
    call = CallDepth(
        callee="validate", line=3, hops_in_file=1, hops_in_other_files=0, other_files=[], ended_at=WalkEnd.REAL_LOGIC
    )
    report = DepthReport(function="total", path="app/service.py", calls=[call])

    prepared = _prepared_file(call_depth_reports=[report])

    assert prepared.call_depth_reports == [report]


def test_prepared_files_do_not_share_the_default_reports_list() -> None:
    first, second = _prepared_file(), _prepared_file()

    first.call_depth_reports.append(DepthReport(function="f", path="a.py", calls=[]))

    assert second.call_depth_reports == []
