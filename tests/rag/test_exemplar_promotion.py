"""
    Tests for the promotion gate: what a panel's verdicts mean, and that
    nothing reaches the corpus without a unanimous yes. The panel and the
    store are faked, so no LLM or embedding call happens here.
"""
import pytest

from code_reviewer.consensus.vote import ConsensusVoteError, VoteResult, VoteVerdict
from code_reviewer.rag.errors import UnsupportedExemplarPrincipleError
from code_reviewer.rag.exemplar_promotion import (
    ExemplarCandidate,
    ExemplarPromoter,
    PromotionOutcome,
)
from code_reviewer.rag.exemplars import ExemplarSource
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import CodeKey

CANDIDATE_CODE = "class PaymentProcessor:\n    def charge(self, method):\n        return method.charge()\n"


class FakeVote:
    """Stand-in for Vote: returns fixed verdicts and records the question asked."""

    def __init__(self, verdicts: list[bool] | None = None, error: Exception | None = None) -> None:
        self._verdicts = verdicts or []
        self._error = error
        self.prompt: str | None = None
        self.content: str | None = None

    def vote_multi_provider(self, system_prompt: str, content: str, voters: list) -> VoteResult:
        self.prompt = system_prompt
        self.content = content
        if self._error is not None:
            raise self._error
        return VoteResult(votes=[VoteVerdict(reasoning="r", verdict=v) for v in self._verdicts])


class FakeStore:
    """Stand-in for ExemplarStore, recording what it was asked to write."""

    def __init__(self) -> None:
        self.added: list[tuple[RepoData, CodeKey, ExemplarSource]] = []

    def add_exemplar(self, repo_data: RepoData, code_key: CodeKey, source: ExemplarSource) -> None:
        self.added.append((repo_data, code_key, source))


def _candidate(code_key: CodeKey = CodeKey.SOLID1) -> ExemplarCandidate:
    return ExemplarCandidate(
        repo_data=RepoData(repo_id="r1", commit_sha="abc", owner_id="o1"),
        code_key=code_key,
        source=ExemplarSource("billing/payment.py", CANDIDATE_CODE),
    )


def test_unanimous_yes_is_promoted() -> None:
    """Verify agreement across the whole panel is what promotes a candidate."""
    promoter = ExemplarPromoter(FakeStore(), voters=[], vote=FakeVote([True, True, True]))

    assert promoter.promote(_candidate()) is PromotionOutcome.PROMOTED


def test_unanimous_yes_writes_the_candidate_to_the_corpus() -> None:
    """Verify a promotion actually reaches the store, not just the outcome."""
    store = FakeStore()

    ExemplarPromoter(store, voters=[], vote=FakeVote([True, True, True])).promote(_candidate())

    assert store.added[0][2].code == CANDIDATE_CODE


def test_unanimous_no_is_rejected() -> None:
    """Verify a panel agreeing the candidate is weak rejects it outright,
    rather than passing it to a human who has no new evidence to add."""
    promoter = ExemplarPromoter(FakeStore(), voters=[], vote=FakeVote([False, False, False]))

    assert promoter.promote(_candidate()) is PromotionOutcome.REJECTED


def test_split_panel_needs_review() -> None:
    """Verify disagreement is reported as uncertainty rather than resolved by
    majority — a contested exemplar shapes every future review that finds it."""
    promoter = ExemplarPromoter(FakeStore(), voters=[], vote=FakeVote([True, True, False]))

    assert promoter.promote(_candidate()) is PromotionOutcome.NEEDS_REVIEW


def test_a_split_panel_writes_nothing() -> None:
    """Verify only a unanimous yes reaches the corpus, since a stored exemplar
    cannot be un-taught once other reviews start retrieving it."""
    store = FakeStore()

    ExemplarPromoter(store, voters=[], vote=FakeVote([True, False, True])).promote(_candidate())

    assert store.added == []


def test_a_rejected_candidate_writes_nothing() -> None:
    """Verify a rejection leaves the corpus untouched."""
    store = FakeStore()

    ExemplarPromoter(store, voters=[], vote=FakeVote([False, False, False])).promote(_candidate())

    assert store.added == []


def test_the_judges_are_never_told_the_review_score() -> None:
    """Verify the panel judges the code alone. Telling judges it already
    scored 100 would make them agree with the agent they exist to check."""
    vote = FakeVote([True, True, True])

    ExemplarPromoter(FakeStore(), voters=[], vote=vote).promote(_candidate())

    assert vote.content == CANDIDATE_CODE


def test_an_out_of_scope_principle_is_rejected_before_voting() -> None:
    """Verify a principle no agent retrieves never reaches the panel — storing
    it would leave a row nothing can ever read, at the cost of three LLM calls."""
    vote = FakeVote([True, True, True])

    with pytest.raises(UnsupportedExemplarPrincipleError):
        ExemplarPromoter(FakeStore(), voters=[], vote=vote).promote(_candidate(CodeKey.VAR))

    assert vote.prompt is None


def test_a_failed_vote_propagates() -> None:
    """Verify a judge outage surfaces rather than being read as a rejection,
    which would silently discard a candidate nobody actually judged."""
    vote = FakeVote(error=ConsensusVoteError("judge timed out"))

    with pytest.raises(ConsensusVoteError):
        ExemplarPromoter(FakeStore(), voters=[], vote=vote).promote(_candidate())
