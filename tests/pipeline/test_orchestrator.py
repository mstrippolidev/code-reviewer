"""
    Tests for review_submission — the entry point wiring
    prepare_files_for_pipeline's output into agent dispatch. The intake
    screen is monkeypatched out (LLM-backed, already covered by its own
    tests); agents are faked so these exercise the wiring only.
"""
import pytest

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline import orchestrator
from code_reviewer.pipeline.orchestrator import review_submission
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, SizeStatus
from code_reviewer.schemas.submission import SubmittedFile


class FakeAgent:
    """Duck-typed stand-in for AgentBase/FileSizeAwareAgentBase/
    CoverageGapAgent — dispatch only ever calls get_agent_key/
    execute_agent/execute_agent_batch."""

    def __init__(self, code_key: CodeKey) -> None:
        self._code_key = code_key

    def get_agent_key(self) -> CodeKey:
        return self._code_key

    def execute_agent(self, code: str, file_path: str | None = None, size_status: SizeStatus | None = None) -> AgentOutput:
        entry = AgentReviewEntry(file_path=file_path, code_key=self._code_key, incidents=[])
        return AgentOutput(review=[entry])

    def execute_agent_batch(self, chunks: list[str], file_path: str | None = None) -> list[AgentOutput]:
        return [self.execute_agent(chunk, file_path) for chunk in chunks]


@pytest.fixture
def container() -> AgentsContainer:
    return AgentsContainer(
        file_agents=[FakeAgent(CodeKey.COH)],
        chunk_agents=[FakeAgent(CodeKey.VAR)],
        tcase_agent=FakeAgent(CodeKey.TCASE),
    )


@pytest.fixture(autouse=True)
def skip_intake_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "run_intake_screen", lambda content: None)


def _file(file_path: str, content: str = "x = 1\n") -> SubmittedFile:
    return SubmittedFile(file_path=file_path, content=content)


def test_returns_one_entry_per_agent_for_a_single_file(container: AgentsContainer) -> None:
    entries, skipped = review_submission([_file("a.py")], container)

    assert {entry.code_key for entry in entries} == {CodeKey.COH, CodeKey.VAR, CodeKey.TCASE}
    assert skipped == []


def test_flattens_entries_across_multiple_files(container: AgentsContainer) -> None:
    entries, _ = review_submission([_file("a.py"), _file("b.py")], container)

    assert {entry.file_path for entry in entries} == {"a.py", "b.py"}
    assert len(entries) == 6


def test_no_files_returns_no_entries_and_no_skips(container: AgentsContainer) -> None:
    entries, skipped = review_submission([], container)

    assert entries == []
    assert skipped == []


def test_file_over_the_hard_line_limit_is_skipped_not_reviewed(
    container: AgentsContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_file_lines", 10)
    oversized = _file("too_big.py", content="x = 1\n" * 20)

    entries, skipped = review_submission([oversized], container)

    assert entries == []
    assert [skipped_file.file_path for skipped_file in skipped] == ["too_big.py"]
