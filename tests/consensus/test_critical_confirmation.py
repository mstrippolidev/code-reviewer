"""
    Tests for CriticalConfirmation's own plumbing: which incidents it puts to
    the panel, what it does with the panel's answer, and how it fails. The
    panel itself is faked rather than calling real judges.
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from code_reviewer.consensus import critical_confirmation as module
from code_reviewer.consensus.critical_confirmation import (
    CriticalConfirmation,
    CriticalConfirmationError,
)
from code_reviewer.consensus.vote import ConsensusVoteError, VoteResult, VoteVerdict
from code_reviewer.prompts.critical_confirmation import CRITICAL_CONFIRMATION_PROMPTS
from code_reviewer.schemas.review import (
    AgentOutput,
    AgentReviewEntry,
    CodeKey,
    Incident,
    Priority,
)


def _incident(priority: Priority) -> Incident:
    return Incident(
        priority=priority,
        line_position="10-12",
        description="swallowed exception around the charge call",
        advice="raise a custom exception",
    )


def _state(incidents: list[Incident]) -> dict:
    output = AgentOutput(
        review=[AgentReviewEntry(code_key=CodeKey.ERR, incidents=incidents, rating=80)]
    )
    return {
        "structured_response": output,
        "messages": [HumanMessage(content="def charge(): ..."), AIMessage(content="done")],
    }


def _patch_panel(monkeypatch: pytest.MonkeyPatch, verdicts: list[bool]) -> None:
    votes = [VoteVerdict(reasoning="r", verdict=v) for v in verdicts]
    monkeypatch.setattr(
        module.Vote, "vote_multi_provider", lambda self, prompt, content, judges: VoteResult(votes=votes)
    )


def _middleware() -> CriticalConfirmation:
    return CriticalConfirmation(CodeKey.ERR, judges=["judge-a", "judge-b", "judge-c"])


def test_unanimous_panel_keeps_the_incident_critical(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a critical the whole panel upholds stays critical."""
    _patch_panel(monkeypatch, [True, True, True])
    state = _state([_incident(Priority.CRITICAL)])

    _middleware().after_model(state, runtime=None)

    assert state["structured_response"].review[0].incidents[0].priority == Priority.CRITICAL


def test_split_panel_downgrades_the_incident_to_high(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a critical the panel disagrees over drops to high, since a
    single critical rejects a PR on its own."""
    _patch_panel(monkeypatch, [True, True, False])
    state = _state([_incident(Priority.CRITICAL)])

    _middleware().after_model(state, runtime=None)

    assert state["structured_response"].review[0].incidents[0].priority == Priority.HIGH


def test_unanimous_rejection_downgrades_the_incident_to_high(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a critical the whole panel rejects drops to high — unanimity
    alone is not confirmation, it has to be unanimous agreement on true."""
    _patch_panel(monkeypatch, [False, False, False])
    state = _state([_incident(Priority.CRITICAL)])

    _middleware().after_model(state, runtime=None)

    assert state["structured_response"].review[0].incidents[0].priority == Priority.HIGH


def test_non_critical_incident_is_never_put_to_the_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify only critical incidents cost panel calls; every other priority
    passes through untouched."""
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("the panel must not be consulted for a non-critical incident")

    monkeypatch.setattr(module.Vote, "vote_multi_provider", _fail)
    state = _state([_incident(Priority.HIGH)])

    _middleware().after_model(state, runtime=None)

    assert state["structured_response"].review[0].incidents[0].priority == Priority.HIGH


def test_panel_failure_downgrades_rather_than_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a panel outage cannot leave an unconfirmed critical standing,
    since a critical rejects a PR by itself."""
    def _raise(*args: object, **kwargs: object) -> None:
        raise ConsensusVoteError("panel down")

    monkeypatch.setattr(module.Vote, "vote_multi_provider", _raise)
    state = _state([_incident(Priority.CRITICAL)])

    _middleware().after_model(state, runtime=None)

    assert state["structured_response"].review[0].incidents[0].priority == Priority.HIGH


def test_no_structured_response_is_left_alone() -> None:
    """Verify a tool-loop turn, which carries no structured output yet,
    produces no state update."""
    state = {"structured_response": None, "messages": [HumanMessage(content="code")]}

    assert _middleware().after_model(state, runtime=None) is None


def test_empty_panel_skips_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an unconfigured panel leaves findings untouched rather than
    downgrading every critical it cannot check."""
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("no panel means no vote")

    monkeypatch.setattr(module.Vote, "vote_multi_provider", _fail)
    state = _state([_incident(Priority.CRITICAL)])

    CriticalConfirmation(CodeKey.ERR, judges=[]).after_model(state, runtime=None)

    assert state["structured_response"].review[0].incidents[0].priority == Priority.CRITICAL


def test_missing_reviewed_code_raises() -> None:
    """Verify a state with no human message fails loudly rather than judging
    a finding against no code at all."""
    state = {
        "structured_response": AgentOutput(
            review=[AgentReviewEntry(code_key=CodeKey.ERR, incidents=[_incident(Priority.CRITICAL)])]
        ),
        "messages": [AIMessage(content="no request here")],
    }

    with pytest.raises(CriticalConfirmationError):
        _middleware().after_model(state, runtime=None)


def test_every_code_reviewing_agent_has_a_confirmation_prompt() -> None:
    """Verify every agent that reviews source code can confirm its own
    criticals. DRY is excluded: it never sees code, only an assembled
    duplication report, so there is no code for a judge to check against."""
    assert set(CRITICAL_CONFIRMATION_PROMPTS) == set(CodeKey) - {CodeKey.DRY}
