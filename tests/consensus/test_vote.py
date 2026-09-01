"""
    Tests for Vote's own plumbing: branching one call per voter, aggregating
    verdicts, and reporting agreement. These exercise our fan-out and
    aggregation logic, not prompt quality, so create_agent is faked rather
    than calling a real LLM.
"""
import pytest

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.consensus.vote import ConsensusVoteError, Vote, VoteVerdict
from code_reviewer.consensus import vote as vote_module


class FakeLLMInterface(LLMInterface):
    """Minimal LLMInterface stand-in — create_raw_model is overridden so
    tests never touch a real provider's init_chat_model wiring."""

    def create_raw_model(self) -> None:
        return None

    def _get_model_name(self) -> str:
        return "fake-model"

    def _get_model_provider(self) -> str:
        return "fake"

    def _get_base_url(self) -> str:
        return "http://fake"

    def build_response_format(self, schema: type) -> type:
        return schema


class FakeAgent:
    """Stand-in for the LangGraph agent create_agent would normally build."""

    def __init__(self, verdict: VoteVerdict) -> None:
        self._verdict = verdict

    def invoke(self, messages: dict) -> dict:
        return {"structured_response": self._verdict}


def _patch_create_agent(monkeypatch: pytest.MonkeyPatch, verdicts: list[VoteVerdict]) -> None:
    """Makes each successive create_agent() call in voter order return a
    FakeAgent carrying the next verdict in verdicts."""
    remaining = iter(verdicts)
    monkeypatch.setattr(vote_module, "create_agent", lambda **kwargs: FakeAgent(next(remaining)))


def _verdict(is_true: bool) -> VoteVerdict:
    return VoteVerdict(verdict=is_true, reasoning="test reasoning")


def test_vote_multi_provider_is_unanimous_when_all_voters_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unanimous is True when every voter reaches the same verdict."""
    _patch_create_agent(monkeypatch, [_verdict(True), _verdict(True), _verdict(True)])
    voters = [FakeLLMInterface(), FakeLLMInterface(), FakeLLMInterface()]

    result = Vote().vote_multi_provider("is this good?", "candidate code", voters)

    assert result.unanimous is True


def test_vote_multi_provider_is_unanimous_when_all_voters_agree_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unanimous is True when every voter agrees on False, not just
    True — unanimity depends on agreement, never on which side voters land."""
    _patch_create_agent(monkeypatch, [_verdict(False), _verdict(False), _verdict(False)])
    voters = [FakeLLMInterface(), FakeLLMInterface(), FakeLLMInterface()]

    result = Vote().vote_multi_provider("is this good?", "candidate code", voters)

    assert result.unanimous is True


def test_vote_multi_provider_is_not_unanimous_on_a_split(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unanimous is False when voters disagree, matching config A's
    3-0 vs 2-1 outcomes described in the consensus spec."""
    _patch_create_agent(monkeypatch, [_verdict(True), _verdict(True), _verdict(False)])
    voters = [FakeLLMInterface(), FakeLLMInterface(), FakeLLMInterface()]

    result = Vote().vote_multi_provider("is this good?", "candidate code", voters)

    assert result.unanimous is False


def test_vote_preserves_voter_order_in_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify votes come back in the same order voters were given, even
    though RunnableParallel may run the branches concurrently."""
    _patch_create_agent(monkeypatch, [_verdict(True), _verdict(False), _verdict(True)])
    voters = [FakeLLMInterface(), FakeLLMInterface(), FakeLLMInterface()]

    result = Vote().vote_multi_provider("is this real?", "finding text", voters)

    assert [vote.verdict for vote in result.votes] == [True, False, True]


def test_vote_raises_consensus_vote_error_when_a_voter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a failing voter surfaces as ConsensusVoteError, not a raw
    exception from whatever provider call failed underneath."""

    def _raise_on_invoke(**kwargs: object) -> FakeAgent:
        class _FailingAgent:
            def invoke(self, messages: dict) -> dict:
                raise RuntimeError("boom")

        return _FailingAgent()

    monkeypatch.setattr(vote_module, "create_agent", _raise_on_invoke)
    voters = [FakeLLMInterface()]

    with pytest.raises(ConsensusVoteError):
        Vote().vote_multi_provider("is this good?", "candidate code", voters)
