"""
    Tests for AgentBase's batch execution mechanism: payload shape,
    result unpacking, and per-result stamping. These exercise our own
    plumbing around LangChain's batch(), not prompt quality, so the
    underlying LangGraph agent is faked rather than calling a real LLM.
"""
import pytest

from code_reviewer.agents.base import AgentBase, AgentInvocationError
from code_reviewer.config.settings import get_settings
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey


def _fake_output(code_key: CodeKey, rating: int = 100) -> AgentOutput:
    return AgentOutput(review=[AgentReviewEntry(code_key=code_key, incidents=[], rating=rating)])


@pytest.fixture
def agent() -> AgentBase:
    return AgentBase(CodeKey.VAR, "test prompt")


def test_batch_sends_one_payload_per_chunk_in_order(agent: AgentBase) -> None:
    captured = {}

    def fake_batch(payloads, config=None):
        captured["payloads"] = payloads
        return [{"structured_response": _fake_output(CodeKey.VAR)} for _ in payloads]

    agent._agent.batch = fake_batch

    agent.execute_agent_batch(["chunk one", "chunk two"], file_path="f.py")

    assert captured["payloads"] == [
        {"messages": [{"role": "user", "content": "chunk one"}]},
        {"messages": [{"role": "user", "content": "chunk two"}]},
    ]


def test_batch_uses_max_batch_concurrency_from_settings(agent: AgentBase, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_batch_concurrency", 7)
    captured = {}

    def fake_batch(payloads, config=None):
        captured["config"] = config
        return [{"structured_response": _fake_output(CodeKey.VAR)} for _ in payloads]

    agent._agent.batch = fake_batch

    agent.execute_agent_batch(["chunk one"], file_path="f.py")

    assert captured["config"] == {"max_concurrency": 7}


def test_batch_returns_one_result_per_chunk_in_order(agent: AgentBase) -> None:
    outputs = [_fake_output(CodeKey.VAR, rating=90), _fake_output(CodeKey.VAR, rating=70)]
    agent._agent.batch = lambda payloads, config=None: [{"structured_response": output} for output in outputs]

    results = agent.execute_agent_batch(["chunk one", "chunk two"], file_path="f.py")

    assert len(results) == 2
    assert results[0].review[0].rating == 90
    assert results[1].review[0].rating == 70


def test_batch_stamps_file_path_and_code_key_on_every_result(agent: AgentBase) -> None:
    agent._agent.batch = lambda payloads, config=None: [
        {"structured_response": _fake_output(CodeKey.VAR)} for _ in payloads
    ]

    results = agent.execute_agent_batch(["chunk one", "chunk two"], file_path="my_file.py")

    assert all(entry.file_path == "my_file.py" for result in results for entry in result.review)
    assert all(entry.code_key == CodeKey.VAR for result in results for entry in result.review)


def test_batch_failure_raises_agent_invocation_error(agent: AgentBase) -> None:
    def failing_batch(payloads, config=None):
        raise RuntimeError("boom")

    agent._agent.batch = failing_batch

    with pytest.raises(AgentInvocationError):
        agent.execute_agent_batch(["chunk one"], file_path="f.py")


def test_batch_with_empty_chunk_list_returns_empty_results(agent: AgentBase) -> None:
    agent._agent.batch = lambda payloads, config=None: []

    results = agent.execute_agent_batch([], file_path="f.py")

    assert results == []
