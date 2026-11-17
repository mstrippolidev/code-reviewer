"""
    Real-model check of the output token cap: a reply cut off at the cap fails the agent and is not retried.
    Validated against OpenRouter, since a small local model says more about itself than about the cap.
"""
from unittest.mock import Mock

import pytest

from code_reviewer.agents.base import AgentInvocationError, FileReviewMeta
from code_reviewer.agents.coupling import CouplingAgent
from code_reviewer.agents.llm.output_cap import OutputTruncatedError, RaiseOnTruncatedOutput
from code_reviewer.agents.naming import NamingAgent
from code_reviewer.config.settings import get_settings
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm

TINY_CAP = 8


def _causes_of(error: BaseException) -> list[BaseException]:
    chain = []
    while error is not None:
        chain.append(error)
        error = error.__cause__
    return chain


def test_a_reply_cut_off_at_the_cap_fails_the_agent_after_one_call(
    small_llm, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a truncated reply raises OutputTruncatedError instead of being parsed or retried."""
    monkeypatch.setattr(get_settings(), "llm_max_output_tokens", TINY_CAP)
    calls: list[int] = []
    original = RaiseOnTruncatedOutput.on_llm_end

    def counting(self, response, **kwargs):
        calls.append(1)
        return original(self, response, **kwargs)

    monkeypatch.setattr(RaiseOnTruncatedOutput, "on_llm_end", counting)
    agent = NamingAgent(llm=small_llm)

    with pytest.raises(AgentInvocationError) as raised:
        agent.execute_agent(load_fixture("naming/bad_abbreviations.py"), file_path="bad_abbreviations.py")

    assert any(isinstance(cause, OutputTruncatedError) for cause in _causes_of(raised.value))
    assert len(calls) == 1


def test_a_cut_off_also_fails_an_agent_that_carries_a_tool(small_llm, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the tool-call output format, which COUP and ARCH use, is stopped too, not retried as a schema error."""
    monkeypatch.setattr(get_settings(), "llm_max_output_tokens", TINY_CAP)
    agent = CouplingAgent(llm=small_llm, rag_manager=Mock(spec=LlamaIndexRagManager))
    review_meta = FileReviewMeta(repo_data=RepoData(repo_id="1", commit_sha="abc", owner_id="1"))

    with pytest.raises(AgentInvocationError) as raised:
        agent.execute_agent(
            load_fixture("coup/circular_dependency_violation.py"),
            file_path="circular_dependency_violation.py",
            review_meta=review_meta,
        )

    assert any(isinstance(cause, OutputTruncatedError) for cause in _causes_of(raised.value))
