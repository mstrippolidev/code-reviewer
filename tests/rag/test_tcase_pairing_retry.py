"""
    Tests for CorrectiveTestPairingFinder's corrective loop with fake
    collaborators — which calls happen, how often, and what gets returned.
"""
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.tcase_pairing import PairingBuckets, PairingCandidate
from code_reviewer.rag.tcase_pairing_retry import (
    CONFIRMED_TEST_FILE_CAP,
    CorrectiveTestPairingFinder,
    PairingCorrectionTools,
)
from code_reviewer.schemas.rag.tcase_pairing import PairingMatchStatus, PairingVerdict
from code_reviewer.schemas.submission import SubmittedFile

REPO = RepoData(repo_id="1", commit_sha="abc123", owner_id="7")
SOURCE = SubmittedFile(file_path="shop/payment.py", content="def charge(amount):\n    return amount\n")
REWRITTEN_QUERY = "tests that call charge and assert the charged amount"


class FakeFinder:
    """Returns the same candidates on every attempt, recording each attempt's query."""

    def __init__(self, candidates: list[PairingCandidate]) -> None:
        self._candidates = candidates
        self.queries: list[str | None] = []

    def find_candidates(self, repo_data: RepoData, source_file: SubmittedFile, semantic_query: str | None = None) -> PairingBuckets:
        self.queries.append(semantic_query)
        return PairingBuckets(deterministic=[], semantic=list(self._candidates))


class PassThroughReranker:
    def rerank(self, query: str, buckets: PairingBuckets) -> list[PairingCandidate]:
        return [*buckets.deterministic, *buckets.semantic]


class ScriptedJudge:
    """Answers each successive call with the next scripted list of statuses."""

    def __init__(self, statuses_per_call: list[list[PairingMatchStatus]]) -> None:
        self._statuses_per_call = statuses_per_call
        self.calls = 0

    def judge(self, source_file: SubmittedFile, candidates: list[PairingCandidate]) -> list[PairingVerdict]:
        statuses = self._statuses_per_call[self.calls]
        self.calls += 1
        return [
            PairingVerdict(candidate_index=index, status=status, reasoning=f"reason {index}")
            for index, status in enumerate(statuses)
        ]


class RecordingRewriter:
    def __init__(self) -> None:
        self.received_reasons: list[list[str]] = []

    def rewrite(self, source_file: SubmittedFile, rejection_reasons: list[str]) -> str:
        self.received_reasons.append(rejection_reasons)
        return REWRITTEN_QUERY


def _candidates(count: int) -> list[PairingCandidate]:
    return [PairingCandidate(file_path=f"tests/test_{index}.py", content=f"body {index}") for index in range(count)]


def _pairing_finder(
    finder: FakeFinder, judge: ScriptedJudge, rewriter: RecordingRewriter | None = None
) -> CorrectiveTestPairingFinder:
    correction = PairingCorrectionTools(judge=judge, query_rewriter=rewriter or RecordingRewriter())
    return CorrectiveTestPairingFinder(finder, PassThroughReranker(), correction)


MATCH, NO_MATCH, AMBIGUOUS = PairingMatchStatus.MATCH, PairingMatchStatus.NO_MATCH, PairingMatchStatus.AMBIGUOUS


def test_confirmed_match_on_the_first_attempt_returns_it_as_a_submitted_test_file() -> None:
    """Verify a first-attempt match comes back ready for TCASE's pairing content."""
    finder = FakeFinder(_candidates(2))

    test_files = _pairing_finder(finder, ScriptedJudge([[NO_MATCH, MATCH]])).find_test_files(REPO, SOURCE)

    assert test_files == [SubmittedFile(file_path="tests/test_1.py", content="body 1")]


def test_confirmed_match_on_the_first_attempt_never_rewrites_the_query() -> None:
    """Verify the corrective step only runs when the first attempt confirmed nothing."""
    rewriter = RecordingRewriter()

    _pairing_finder(FakeFinder(_candidates(1)), ScriptedJudge([[MATCH]]), rewriter).find_test_files(REPO, SOURCE)

    assert rewriter.received_reasons == []


def test_no_confirmed_match_retries_once_with_the_rewritten_query() -> None:
    """Verify the retry searches with the rewritten query, not the original source again."""
    finder = FakeFinder(_candidates(1))

    _pairing_finder(finder, ScriptedJudge([[NO_MATCH], [MATCH]])).find_test_files(REPO, SOURCE)

    assert finder.queries == [None, REWRITTEN_QUERY]


def test_rewrite_receives_the_judges_reasons_for_every_unconfirmed_candidate() -> None:
    """Verify ambiguous and no_match reasoning both feed the rewrite as steering feedback."""
    rewriter = RecordingRewriter()
    judge = ScriptedJudge([[NO_MATCH, AMBIGUOUS], [NO_MATCH, NO_MATCH]])

    _pairing_finder(FakeFinder(_candidates(2)), judge, rewriter).find_test_files(REPO, SOURCE)

    assert rewriter.received_reasons == [["reason 0", "reason 1"]]


def test_ambiguous_is_never_treated_as_a_confirmed_match() -> None:
    """Verify only a match verdict pairs a test file; ambiguous stays unconfirmed after the retry too."""
    judge = ScriptedJudge([[AMBIGUOUS], [AMBIGUOUS]])

    test_files = _pairing_finder(FakeFinder(_candidates(1)), judge).find_test_files(REPO, SOURCE)

    assert test_files == []


def test_nothing_confirmed_after_the_retry_stops_without_a_third_attempt() -> None:
    """Verify the corrective loop is bounded to exactly one retry."""
    finder = FakeFinder(_candidates(1))

    _pairing_finder(finder, ScriptedJudge([[NO_MATCH], [NO_MATCH]])).find_test_files(REPO, SOURCE)

    assert len(finder.queries) == 2


def test_confirmed_matches_are_capped() -> None:
    """Verify TCASE never receives more than CONFIRMED_TEST_FILE_CAP paired test files."""
    candidate_count = CONFIRMED_TEST_FILE_CAP + 2
    judge = ScriptedJudge([[MATCH] * candidate_count])

    test_files = _pairing_finder(FakeFinder(_candidates(candidate_count)), judge).find_test_files(REPO, SOURCE)

    assert len(test_files) == CONFIRMED_TEST_FILE_CAP
