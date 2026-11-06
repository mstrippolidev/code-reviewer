"""
    Dispatch wiring for a test file reviewed as its own target, with no
    source file to pair it to — both dispatch strategies, fakes only.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import create_engine

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.pipeline import dispatch as dispatch_module
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.structural_hash_store import StructuralHashStore
from code_reviewer.schemas.paired import build_standalone_test_file_content
from code_reviewer.schemas.review import CodeKey, ReviewScope, SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile
from code_reviewer.telemetry.metrics import PipelineMetrics
from tests.metric_points import AGENT_SKIPPED, points_for
from tests.pipeline.test_dispatch import (
    DISPATCH_FUNCTIONS,
    DispatchFn,
    FakeAgent,
    FakeCodeSimilarityIndex,
    FakeDryJudge,
    FakeEmbeddingIndex,
    FakeRerankPostprocessor,
)

TEST_FILE = SubmittedFile(file_path="tests/test_payment.py", content="def test_charge():\n    assert charge(1) == 1\n")


@pytest.fixture
def agents() -> dict[CodeKey, FakeAgent]:
    return {code_key: FakeAgent(code_key) for code_key in (CodeKey.COH, CodeKey.CMPLX, CodeKey.VAR, CodeKey.ERR, CodeKey.CMT, CodeKey.TCASE)}


@pytest.fixture
def dry_judge() -> FakeDryJudge:
    return FakeDryJudge()


@pytest.fixture
def container(agents: dict[CodeKey, FakeAgent], dry_judge: FakeDryJudge) -> AgentsContainer:
    return AgentsContainer(
        file_agents=[agents[CodeKey.COH], agents[CodeKey.CMPLX]],
        chunk_agents=[agents[CodeKey.VAR], agents[CodeKey.ERR], agents[CodeKey.CMT]],
        tcase_agent=agents[CodeKey.TCASE],
        dry_judge=dry_judge,
        rag_manager=FakeEmbeddingIndex(),
        structural_hash_store=StructuralHashStore(engine=create_engine("sqlite:///:memory:"), schema_name=None),
        code_similarity_index=FakeCodeSimilarityIndex(),
        history_match_reranker=HistoryMatchReranker(max_candidates=5, postprocessor=FakeRerankPostprocessor()),
    )


def _standalone_prepared_file() -> PreparedFile:
    return PreparedFile(
        source_file=TEST_FILE,
        size_status=SizeStatus.NORMAL,
        review_scope=ReviewScope.TEST_FILE_STANDALONE,
    )


@DISPATCH_FUNCTIONS
def test_standalone_test_file_is_reviewed_only_by_hygiene_agents_and_tcase(
    dispatch: DispatchFn, container: AgentsContainer
) -> None:
    """Verify only VAR, ERR, CMT and TCASE run on a test file with no source to pair it to.

    Architecture and structure agents judge production-code concerns that
    don't transfer to test code, and DRY has no source chunk to compare.
    """
    entries = dispatch(_standalone_prepared_file(), container)

    assert {entry.code_key for entry in entries} == {CodeKey.VAR, CodeKey.ERR, CodeKey.CMT, CodeKey.TCASE}


@DISPATCH_FUNCTIONS
def test_standalone_test_file_never_reaches_a_file_agent(
    dispatch: DispatchFn, container: AgentsContainer, agents: dict[CodeKey, FakeAgent]
) -> None:
    """Verify a file agent is never called, not just filtered out of the results."""
    dispatch(_standalone_prepared_file(), container)

    assert agents[CodeKey.COH].execute_agent_calls == []


@DISPATCH_FUNCTIONS
def test_standalone_test_file_never_reaches_the_dry_judge(
    dispatch: DispatchFn, container: AgentsContainer, dry_judge: FakeDryJudge
) -> None:
    """Verify DRY spends no judge call on a standalone test file."""
    dispatch(_standalone_prepared_file(), container)

    assert dry_judge.judge_calls == []


@DISPATCH_FUNCTIONS
def test_standalone_test_file_sends_tcase_the_test_design_prompt_shape(
    dispatch: DispatchFn, container: AgentsContainer, agents: dict[CodeKey, FakeAgent]
) -> None:
    """Verify TCASE receives the standalone header its prompt keys the test-design branch off.

    A Pairing-shaped "SOURCE FILE:" message would instead ask TCASE for
    coverage gaps against a source that isn't there.
    """
    dispatch(_standalone_prepared_file(), container)

    tcase_code = agents[CodeKey.TCASE].execute_agent_calls[0][0]
    assert tcase_code == build_standalone_test_file_content(TEST_FILE)


@DISPATCH_FUNCTIONS
def test_standalone_test_file_counts_each_left_out_agent_as_skipped(
    dispatch: DispatchFn,
    container: AgentsContainer,
    monkeypatch: pytest.MonkeyPatch,
    isolated_pipeline_metrics: PipelineMetrics,
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify the two file agents and DRY are counted with the standalone reason, and the agents that ran are not."""
    monkeypatch.setattr(dispatch_module, "pipeline_metrics", isolated_pipeline_metrics)

    dispatch(_standalone_prepared_file(), container)

    skipped = {
        point.attributes["code_reviewer.code_key"]: point.value
        for point in points_for(metric_reader, AGENT_SKIPPED)
        if point.attributes["code_reviewer.reason"] == "standalone_test_file"
    }
    assert skipped == {"COH": 1, "CMPLX": 1, "DRY": 1}
