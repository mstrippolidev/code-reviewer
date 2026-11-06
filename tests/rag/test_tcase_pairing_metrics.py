"""
    Tests that TCASE's corpus-wide test-file lookup reports where its time goes and whether it found a test
    file. Fake collaborators throughout: no vector store, embedding or LLM call.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.rag import tcase_pairing, tcase_pairing_retry
from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.tcase_pairing import PairingCandidateFinder, PairingEvidenceSources
from code_reviewer.rag.tcase_pairing_retry import CorrectiveTestPairingFinder, PairingCorrectionTools
from code_reviewer.schemas.rag.tcase_pairing import PairingMatchStatus
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import (
    RAG_PAIRING_DURATION,
    RAG_PAIRING_LOOKUPS,
    RAG_RETRIEVAL_DURATION,
    point_with,
    points_for,
)
from tests.rag.test_tcase_pairing import REPO, SOURCE, FakeCodeSimilarityIndex, FakeEmbeddingIndex
from tests.rag.test_tcase_pairing_retry import (
    FakeFinder,
    PassThroughReranker,
    RecordingRewriter,
    ScriptedJudge,
    _candidates,
)

_SOURCE_LABEL = "code_reviewer.source"
_OUTCOME_LABEL = "code_reviewer.outcome"
_RESULT_LABEL = "code_reviewer.result"
MATCH, NO_MATCH = PairingMatchStatus.MATCH, PairingMatchStatus.NO_MATCH


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points both pairing modules at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(tcase_pairing, "rag_metrics", isolated_rag_metrics)
    monkeypatch.setattr(tcase_pairing_retry, "rag_metrics", isolated_rag_metrics)


def _candidate_finder(embedding_index: FakeEmbeddingIndex) -> PairingCandidateFinder:
    return PairingCandidateFinder(PairingEvidenceSources(embedding_index, FakeCodeSimilarityIndex()))


def _stage_count(metric_reader: InMemoryMetricReader, source: str) -> int:
    return point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE_LABEL: source}).count


def test_the_naming_match_the_dense_search_and_the_lexical_search_are_each_timed_once(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify one find_candidates call times its three searches under the pairing sources."""
    _candidate_finder(FakeEmbeddingIndex(indexed_paths=[])).find_candidates(REPO, SOURCE)

    assert [_stage_count(metric_reader, source) for source in ("pairing_names", "pairing_semantic", "pairing_lexical")] == [1, 1, 1]


def test_a_rewritten_query_is_timed_as_the_same_dense_stage(metric_reader: InMemoryMetricReader) -> None:
    """Verify the retry's search by query lands in the same series, so the stage reads as one."""
    _candidate_finder(FakeEmbeddingIndex(indexed_paths=[])).find_candidates(REPO, SOURCE, "tests that call charge")

    assert _stage_count(metric_reader, "pairing_semantic") == 1


def test_every_candidate_content_lookup_is_timed(metric_reader: InMemoryMetricReader) -> None:
    """Verify the one-by-one chunk fetches show up as one point each, since their count is the cost."""
    indexed = ["tests/test_payment.py", "tests/payment_test.py"]

    _candidate_finder(FakeEmbeddingIndex(indexed_paths=indexed)).find_candidates(REPO, SOURCE)

    assert _stage_count(metric_reader, "pairing_file_lookup") == 2


def test_the_pairing_stages_do_not_share_a_series_with_dry_search(metric_reader: InMemoryMetricReader) -> None:
    """Verify TCASE's searches leave DRY's semantic and lexical series untouched."""
    _candidate_finder(FakeEmbeddingIndex(indexed_paths=[])).find_candidates(REPO, SOURCE)

    sources = {point.attributes[_SOURCE_LABEL] for point in points_for(metric_reader, RAG_RETRIEVAL_DURATION)}
    assert sources.isdisjoint({"semantic", "lexical", "code", "structural"})


def test_a_failing_stage_is_counted_as_failed_and_still_raises(metric_reader: InMemoryMetricReader) -> None:
    """Verify an outage in the index shows in the stage's outcome and still reaches the caller."""

    class FailingIndex(FakeEmbeddingIndex):
        def list_indexed_file_paths(self, repo_id: str, owner_id: str | None) -> list[str]:
            raise VectorStoreQueryError("index down")

    with pytest.raises(VectorStoreQueryError):
        _candidate_finder(FailingIndex(indexed_paths=[])).find_candidates(REPO, SOURCE)

    failed = point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE_LABEL: "pairing_names", _OUTCOME_LABEL: "failed"})
    assert failed.count == 1


def _corrective_finder(judge: ScriptedJudge, rewriter: RecordingRewriter) -> CorrectiveTestPairingFinder:
    correction = PairingCorrectionTools(judge=judge, query_rewriter=rewriter)
    return CorrectiveTestPairingFinder(FakeFinder(_candidates(2)), PassThroughReranker(), correction)


def test_a_match_on_the_first_attempt_is_counted_and_never_asks_for_a_rewrite(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify the cheap path is recorded as such."""
    rewriter = RecordingRewriter()

    _corrective_finder(ScriptedJudge([[MATCH, NO_MATCH]]), rewriter).find_test_files(REPO, SOURCE)

    assert point_with(metric_reader, RAG_PAIRING_LOOKUPS, {_RESULT_LABEL: "found_first_try"}).value == 1
    assert rewriter.received_reasons == []


def test_a_match_only_after_the_rewrite_is_counted_apart_from_a_first_try(metric_reader: InMemoryMetricReader) -> None:
    """Verify the correction's success is its own series, so its worth can be judged."""
    _corrective_finder(ScriptedJudge([[NO_MATCH, NO_MATCH], [MATCH, NO_MATCH]]), RecordingRewriter()).find_test_files(
        REPO, SOURCE
    )

    assert point_with(metric_reader, RAG_PAIRING_LOOKUPS, {_RESULT_LABEL: "found_after_rewrite"}).value == 1


def test_a_lookup_that_finds_nothing_even_after_the_rewrite_is_counted_as_not_found(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify the correction failing is visible."""
    _corrective_finder(ScriptedJudge([[NO_MATCH, NO_MATCH], [NO_MATCH, NO_MATCH]]), RecordingRewriter()).find_test_files(
        REPO, SOURCE
    )

    assert point_with(metric_reader, RAG_PAIRING_LOOKUPS, {_RESULT_LABEL: "not_found"}).value == 1


def test_one_lookup_adds_one_duration_point_in_the_completed_outcome(metric_reader: InMemoryMetricReader) -> None:
    """Verify the whole lookup, retry included, is a single timed unit."""
    _corrective_finder(ScriptedJudge([[NO_MATCH, NO_MATCH], [MATCH, NO_MATCH]]), RecordingRewriter()).find_test_files(
        REPO, SOURCE
    )

    assert point_with(metric_reader, RAG_PAIRING_DURATION, {_OUTCOME_LABEL: "completed"}).count == 1


def test_a_lookup_that_raises_is_timed_as_failed_records_no_result_and_still_raises(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify a judge outage is visible in the duration series and does not pass for "not found"."""

    class BrokenJudge:
        def judge(self, source_file: object, candidates: object) -> list:
            raise RuntimeError("judge down")

    correction = PairingCorrectionTools(judge=BrokenJudge(), query_rewriter=RecordingRewriter())
    finder = CorrectiveTestPairingFinder(FakeFinder(_candidates(2)), PassThroughReranker(), correction)

    with pytest.raises(RuntimeError):
        finder.find_test_files(REPO, SOURCE)

    assert point_with(metric_reader, RAG_PAIRING_DURATION, {_OUTCOME_LABEL: "failed"}).count == 1
    assert points_for(metric_reader, RAG_PAIRING_LOOKUPS) == []
