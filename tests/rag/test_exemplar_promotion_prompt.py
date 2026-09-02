"""
    Prompt-quality tests for exemplar promotion, run against a real model.

    A single voter stands in for the panel here. Vote's fan-out and its
    unanimity rule are already covered with fakes in tests/consensus and
    tests/rag/test_exemplar_promotion.py; what is unverifiable without a real
    model is whether one judge, given this question, applies the four
    criteria to real code. One voter makes every verdict unanimous, so the
    outcome reports that judge's decision directly.
"""
import pytest

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.rag.exemplar_promotion import (
    ExemplarCandidate,
    ExemplarPromoter,
    PromotionOutcome,
)
from code_reviewer.rag.exemplars import ExemplarSource
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import CodeKey
from tests.helpers import load_fixture


class FakeStore:
    """Stand-in for ExemplarStore, so a promotion never reaches a real
    vector store or spends an embedding call."""

    def __init__(self) -> None:
        self.added: list[ExemplarSource] = []

    def add_exemplar(self, repo_data: RepoData, code_key: CodeKey, source: ExemplarSource) -> None:
        self.added.append(source)


@pytest.fixture
def promoter(small_llm: LLMInterface) -> ExemplarPromoter:
    return ExemplarPromoter(FakeStore(), voters=[small_llm])


def _candidate(fixture_name: str, code_key: CodeKey) -> ExemplarCandidate:
    return ExemplarCandidate(
        repo_data=RepoData(repo_id="r1", commit_sha="abc", owner_id="o1"),
        code_key=code_key,
        source=ExemplarSource(fixture_name, load_fixture(f"exemplar_promotion/{fixture_name}")),
    )


@pytest.mark.llm
def test_a_substantial_srp_ocp_demonstration_is_promoted(promoter: ExemplarPromoter) -> None:
    """Verify code that actively demonstrates SRP and OCP is accepted — the
    prompt must not be so strict that nothing ever qualifies."""
    candidate = _candidate("worthy_solid1.py", CodeKey.SOLID1)

    assert promoter.promote(candidate) is PromotionOutcome.PROMOTED


@pytest.mark.llm
def test_a_segregated_interface_demonstration_is_promoted(promoter: ExemplarPromoter) -> None:
    """Verify the SOLID2 criteria accept a genuine ISP/DIP demonstration, so
    the prompt works for both principles it is built for."""
    candidate = _candidate("worthy_solid2.py", CodeKey.SOLID2)

    assert promoter.promote(candidate) is PromotionOutcome.PROMOTED


@pytest.mark.llm
def test_a_trivial_getter_is_not_promoted(promoter: ExemplarPromoter) -> None:
    """Verify code with no design decision is rejected. This is the
    circularity the panel exists to break: a getter scores 100 in review
    because nothing is wrong with it, while teaching nothing at all."""
    candidate = _candidate("trivial_getter.py", CodeKey.SOLID1)

    assert promoter.promote(candidate) is not PromotionOutcome.PROMOTED


@pytest.mark.llm
def test_code_teaching_a_bad_habit_is_not_promoted(promoter: ExemplarPromoter) -> None:
    """Verify a fragment that is clean on the target principle but swallows
    an exception and returns None is rejected — promoting it would teach
    that habit to every review that later retrieves it."""
    candidate = _candidate("counter_example_solid1.py", CodeKey.SOLID1)

    assert promoter.promote(candidate) is not PromotionOutcome.PROMOTED


@pytest.mark.llm
def test_a_rejected_candidate_never_reaches_the_store(small_llm: LLMInterface) -> None:
    """Verify the write is genuinely gated on the verdict, with a real judge
    rather than a fake one deciding."""
    store = FakeStore()

    ExemplarPromoter(store, voters=[small_llm]).promote(_candidate("trivial_getter.py", CodeKey.SOLID1))

    assert store.added == []
