import textwrap

from code_reviewer.pipeline.call_depth.report_builder import CallDepthReportBuilder
from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.indexer import FileChunk
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import ReviewScope, SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile

REPO_DATA = RepoData(repo_id="42", commit_sha="abc123", owner_id="owner-1")

ROUTER = """
    from app.service import Service

    def create(service: Service):
        return service.save()
"""

SERVICE = """
    class Service:
        def save(self):
            if self is None:
                return None
            return 1
"""

SAME_FILE_CHAIN = """
    def outer():
        return inner()

    def inner():
        if True:
            return 1
        return 2
"""


class StubRagManager:
    def __init__(self, chunks_by_path: dict[str, list[FileChunk]]) -> None:
        self._chunks_by_path = chunks_by_path
        self.requests: list[str] = []

    def get_file_chunks(self, repo_id: str, owner_id: str | None, file_path: str) -> list[FileChunk]:
        self.requests.append(file_path)
        return self._chunks_by_path.get(file_path, [])


class FailingRagManager:
    def get_file_chunks(self, repo_id: str, owner_id: str | None, file_path: str) -> list[FileChunk]:
        raise VectorStoreQueryError("database is down")


def prepared(
    path: str,
    source: str,
    repo_data: RepoData | None = None,
    size_status: SizeStatus = SizeStatus.NORMAL,
    review_scope: ReviewScope = ReviewScope.FULL,
) -> PreparedFile:
    return PreparedFile(
        source_file=SubmittedFile(file_path=path, content=textwrap.dedent(source)),
        size_status=size_status,
        review_scope=review_scope,
        repo_data=repo_data,
    )


def callees(prepared_file: PreparedFile) -> list[str]:
    return [call.callee for report in prepared_file.call_depth_reports for call in report.calls]


def test_a_call_from_one_pr_file_into_another_is_followed() -> None:
    files = [prepared("app/router.py", ROUTER), prepared("app/service.py", SERVICE)]

    built = CallDepthReportBuilder().build(files)

    assert callees(built[0]) == ["service.save"]


def test_a_submission_with_no_repo_reports_same_file_chains() -> None:
    built = CallDepthReportBuilder().build([prepared("app/chain.py", SAME_FILE_CHAIN)])

    assert callees(built[0]) == ["inner"]


def test_a_call_outside_the_pr_is_not_followed_when_there_is_no_repo() -> None:
    built = CallDepthReportBuilder().build([prepared("app/router.py", ROUTER)])

    assert built[0].call_depth_reports[0].calls[0].ended_at.value == "unresolved"


def test_a_call_outside_the_pr_is_read_from_the_index_for_a_registered_repo() -> None:
    indexed = FileChunk(
        file_path="app/service.py",
        chunk_name="Service",
        start_line=1,
        end_line=5,
        text="explanation",
        code=textwrap.dedent(SERVICE).strip(),
    )
    rag_manager = StubRagManager({"app/service.py": [indexed]})

    built = CallDepthReportBuilder(rag_manager).build([prepared("app/router.py", ROUTER, REPO_DATA)])

    assert rag_manager.requests == ["app/service.py"]
    assert built[0].call_depth_reports[0].calls[0].other_files == ["app/service.py"]


def test_the_index_is_not_used_without_repo_data() -> None:
    rag_manager = StubRagManager({})

    CallDepthReportBuilder(rag_manager).build([prepared("app/router.py", ROUTER)])

    assert rag_manager.requests == []


def test_a_failing_index_lookup_leaves_the_file_with_an_empty_report() -> None:
    built = CallDepthReportBuilder(FailingRagManager()).build([prepared("app/router.py", ROUTER, REPO_DATA)])

    assert built[0].call_depth_reports == []


def test_a_failing_lookup_does_not_blank_the_other_files() -> None:
    files = [prepared("app/router.py", ROUTER, REPO_DATA), prepared("app/chain.py", SAME_FILE_CHAIN, REPO_DATA)]

    built = CallDepthReportBuilder(FailingRagManager()).build(files)

    assert callees(built[1]) == ["inner"]


def test_a_file_that_does_not_parse_keeps_an_empty_report_and_stays_in_the_result() -> None:
    files = [prepared("app/broken.py", "def broken(:\n"), prepared("app/chain.py", SAME_FILE_CHAIN)]

    built = CallDepthReportBuilder().build(files)

    assert ([file.call_depth_reports for file in built][0], callees(built[1])) == ([], ["inner"])


def test_a_file_that_does_not_parse_does_not_block_a_file_that_imports_it() -> None:
    files = [prepared("app/router.py", ROUTER), prepared("app/service.py", "class Service(:\n")]

    built = CallDepthReportBuilder().build(files)

    assert built[0].call_depth_reports[0].calls[0].ended_at.value == "unresolved"


def test_a_file_that_is_not_python_is_not_walked() -> None:
    built = CallDepthReportBuilder().build([prepared("web/app.js", SAME_FILE_CHAIN)])

    assert built[0].call_depth_reports == []


def test_a_standalone_test_file_is_not_walked() -> None:
    standalone = prepared("tests/test_chain.py", SAME_FILE_CHAIN, review_scope=ReviewScope.TEST_FILE_STANDALONE)

    assert CallDepthReportBuilder().build([standalone])[0].call_depth_reports == []


def test_a_file_past_the_hard_size_limit_is_not_walked() -> None:
    oversized = prepared("app/chain.py", SAME_FILE_CHAIN, size_status=SizeStatus.HARD_LIMIT_EXCEEDED)

    assert CallDepthReportBuilder().build([oversized])[0].call_depth_reports == []


def test_the_files_given_are_not_modified() -> None:
    original = prepared("app/chain.py", SAME_FILE_CHAIN)

    CallDepthReportBuilder().build([original])

    assert original.call_depth_reports == []


def test_the_result_keeps_the_order_and_the_count_of_the_files() -> None:
    files = [prepared("a.py", SAME_FILE_CHAIN), prepared("b.js", "x"), prepared("c.py", SAME_FILE_CHAIN)]

    built = CallDepthReportBuilder().build(files)

    assert [file.source_file.file_path for file in built] == ["a.py", "b.js", "c.py"]
