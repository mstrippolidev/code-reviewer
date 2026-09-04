"""
    Tests for the COUP agent (coupling). Content-based checks run against a
    real small local model, per this project's approach to LLM-backed
    tests. The hard-limit short-circuit test needs no LLM at all — COUP is
    a FileSizeAwareAgentBase agent, same as SOLID2/COH, so it isn't marked
    with pytest.mark.llm like the rest of this file.
"""
from unittest.mock import Mock

import pytest

from code_reviewer.agents.base import FileReviewMeta, ReviewContext
from code_reviewer.agents.coupling import CouplingAgent
from code_reviewer.agents.cross_file_evidence_tool import GetFileChunksTool
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import CodeKey, Priority, SizeStatus
from tests.agents.conftest import evidence_tool_calls, report_agent_reasoning
from tests.helpers import load_fixture


@pytest.fixture
def coup_agent(small_llm) -> CouplingAgent:
    return CouplingAgent(llm=small_llm)


@pytest.mark.llm
def test_good_coupling_is_not_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/good_coupling.py")

    result = coup_agent.execute_agent(code, file_path="good_coupling.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.COUP
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_circular_dependency_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/circular_dependency_violation.py")

    result = coup_agent.execute_agent(code, file_path="circular_dependency_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_feature_envy_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/feature_envy_violation.py")

    result = coup_agent.execute_agent(code, file_path="feature_envy_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_inappropriate_intimacy_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/inappropriate_intimacy_violation.py")

    result = coup_agent.execute_agent(code, file_path="inappropriate_intimacy_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_god_object_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/god_object_violation.py")

    result = coup_agent.execute_agent(code, file_path="god_object_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_deep_chain_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/deep_chain_violation.py")

    result = coup_agent.execute_agent(code, file_path="deep_chain_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_file_path_is_stamped_on_every_entry(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/circular_dependency_violation.py")

    result = coup_agent.execute_agent(code, file_path="circular_dependency_violation.py")

    assert all(entry.file_path == "circular_dependency_violation.py" for entry in result.review)


@pytest.mark.llm
def test_high_priority_scenario_is_flagged_high(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/priority_high.py")

    result = coup_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


@pytest.mark.llm
def test_medium_priority_scenario_is_flagged_medium(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/priority_medium.py")

    result = coup_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


@pytest.mark.llm
def test_low_priority_scenario_is_flagged_low(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/priority_low.py")

    result = coup_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_out_of_scope_scenario_is_flagged_low(coup_agent: CouplingAgent) -> None:
    """Common coupling through shared module-level state (two classes with
    no reference to each other, both reading and writing the same global)
    is coupling-adjacent but outside COUP's five in-scope categories, so
    it must still be reported, but only at priority low."""
    code = load_fixture("coup/priority_out_of_scope_low.py")

    result = coup_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


def test_hard_limit_exceeded_short_circuits_without_an_llm_call(coup_agent: CouplingAgent) -> None:
    code = "x\n" * 900

    result = coup_agent.execute_agent(
        code, file_path="huge_file.py", review_meta=FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED)
    )

    entry = result.review[0]
    assert entry.rating == 0
    assert entry.code_key == CodeKey.COUP
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-900"


def test_normal_size_status_does_not_short_circuit(coup_agent: CouplingAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = {}

    def fake_invoke(self, code: str, repo_data=None):
        invoked["called"] = True
        raise AssertionError("stop before a real LLM call")

    monkeypatch.setattr(CouplingAgent, "_invoke", fake_invoke)

    with pytest.raises(AssertionError, match="stop before a real LLM call"):
        coup_agent.execute_agent(
            "x = 1", file_path="tiny.py", review_meta=FileReviewMeta(size_status=SizeStatus.NORMAL)
        )

    assert invoked["called"] is True


def test_without_rag_manager_no_tool_is_wired(small_llm) -> None:
    """Verify a COUP agent built with no rag_manager behaves exactly as
    before — no tool, no context schema."""
    agent = CouplingAgent(llm=small_llm)

    assert agent._build_tools() is None
    assert agent._context_schema() is None
    assert agent._recursion_limit() == 4


def test_with_rag_manager_the_evidence_tool_is_wired(small_llm) -> None:
    """Verify a COUP agent built with a rag_manager gets the evidence
    tool, a matching context schema, and extra recursion headroom for
    the tool round-trip."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    agent = CouplingAgent(llm=small_llm, rag_manager=rag_manager)

    tools = agent._build_tools()

    assert len(tools) == 1
    assert isinstance(tools[0], GetFileChunksTool)
    assert tools[0].rag_manager is rag_manager
    assert agent._context_schema() is ReviewContext
    assert agent._recursion_limit() > 4


# --- Real end-to-end: real Postgres/pgvector, real Ollama embeddings, and
# a real chat LLM (--llm-provider openrouter to run against OpenRouter).
# Nothing here is mocked or faked.

SESSION_CLASS_CODE = (
    "class Session:\n"
    "    def __init__(self):\n"
    "        self._engine = build_engine()\n"
    "        self._connection = None\n"
)

REVIEWED_CODE_REACHING_INTO_SESSION = (
    "from infra.db import Session\n\n\n"
    "class ReportBuilder:\n"
    "    def build(self):\n"
    "        session = Session()\n"
    '        return session._engine.execute("SELECT 1")\n'
)

NOTIFIER_CALLING_BACK_INTO_PROCESSOR_CODE = (
    "class Notifier:\n"
    "    def notify(self, order, processor):\n"
    "        processor.mark_notified(order)\n"
    "        self._log(order)\n"
    "\n"
    "    def _log(self, order):\n"
    "        print(order)\n"
)

REVIEWED_CODE_SUSPECTED_CIRCULAR_DEPENDENCY = (
    "from services.notifier import Notifier\n\n\n"
    "class OrderProcessor:\n"
    "    def __init__(self, notifier: Notifier):\n"
    "        self._notifier = notifier\n"
    "\n"
    "    def process(self, order):\n"
    "        self._notifier.notify(order, processor=self)\n"
    "\n"
    "    def mark_notified(self, order):\n"
    "        order.notified = True\n"
)


def _runtime(context: ReviewContext):
    from langgraph.prebuilt import ToolRuntime as RuntimeCls

    return RuntimeCls(state={}, context=context, config={}, stream_writer=lambda *a, **k: None, tool_call_id=None, store=None)


@pytest.mark.db
@pytest.mark.llm
def test_real_exact_match_narrows_to_the_indexed_symbol(
    integration_rag_manager: LlamaIndexRagManager, integration_repo_data: RepoData
) -> None:
    """Positive: the symbol genuinely exists in real indexed content —
    verify the tool's exact-match tier finds it via a real lookup, not a
    faked one."""
    integration_rag_manager.index_file(integration_repo_data, "infra/db.py", SESSION_CLASS_CODE)
    tool = GetFileChunksTool(rag_manager=integration_rag_manager)

    result = tool._run(
        file_path="infra/db.py",
        imported_symbol_name="Session",
        runtime=_runtime(ReviewContext(repo_id=integration_repo_data.repo_id, owner_id=integration_repo_data.owner_id)),
    )

    assert "Session (1-4):" in result or "Session (" in result
    assert "_engine" in result


@pytest.mark.db
@pytest.mark.llm
def test_real_fallback_also_finds_nothing_when_the_symbol_is_genuinely_absent(
    integration_rag_manager: LlamaIndexRagManager, integration_repo_data: RepoData
) -> None:
    """Negative: the requested symbol exists neither as a chunk name nor
    anywhere in the indexed file's real code — both tiers come back empty
    against real data, and the tool must say so clearly rather than
    returning nothing or raising."""
    integration_rag_manager.index_file(integration_repo_data, "infra/db.py", SESSION_CLASS_CODE)
    tool = GetFileChunksTool(rag_manager=integration_rag_manager)

    result = tool._run(
        file_path="infra/db.py",
        imported_symbol_name="TotallyUnrelatedName",
        runtime=_runtime(ReviewContext(repo_id=integration_repo_data.repo_id, owner_id=integration_repo_data.owner_id)),
    )

    assert result == (
        "'TotallyUnrelatedName' was not found in 'infra/db.py''s indexed content — judge this "
        "dependency on what's visible in this file alone."
    )


@pytest.mark.db
@pytest.mark.llm
def test_real_coup_review_completes_with_the_narrowing_tool_wired(
    integration_rag_manager: LlamaIndexRagManager,
    integration_repo_data: RepoData,
    small_llm: LLMInterface,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full loop, real model: a COUP agent with the real evidence tool
    reviews code that reaches into another class's internals across a
    real cross-file dependency. Spies on GetFileChunksTool._run (without
    changing its behavior) so that if the live model does call the tool,
    we can see what it actually passed — tool-call timing is the model's
    own decision and isn't forced, so this observes rather than requires
    it, but the review must complete successfully either way."""
    integration_rag_manager.index_file(integration_repo_data, "infra/db.py", SESSION_CLASS_CODE)
    observed_calls: list[tuple[str, str | None]] = []
    real_run = GetFileChunksTool._run

    def _spy_run(self, file_path, runtime, imported_symbol_name=None):
        observed_calls.append((file_path, imported_symbol_name))
        return real_run(self, file_path=file_path, runtime=runtime, imported_symbol_name=imported_symbol_name)

    monkeypatch.setattr(GetFileChunksTool, "_run", _spy_run)
    agent = CouplingAgent(llm=small_llm, rag_manager=integration_rag_manager)

    result = agent.execute_agent(
        REVIEWED_CODE_REACHING_INTO_SESSION,
        file_path="report_builder.py",
        review_meta=FileReviewMeta(size_status=SizeStatus.NORMAL, repo_data=integration_repo_data),
    )

    entry = result.review[0]
    assert entry.code_key == CodeKey.COUP
    if observed_calls:
        file_path, symbol_name = observed_calls[0]
        assert file_path == "infra/db.py"
        assert symbol_name in (None, "Session")


@pytest.mark.db
@pytest.mark.llm
def test_real_coup_calls_the_evidence_tool_for_a_suspected_cross_file_cycle(
    integration_rag_manager: LlamaIndexRagManager,
    integration_repo_data: RepoData,
    small_llm: LLMInterface,
) -> None:
    """Full loop, real model: OrderProcessor hands a reference to itself
    into Notifier.notify, so whether this is a real cycle depends entirely
    on what Notifier does with it — the agent cannot answer that from this
    file alone, and must reach for get_file_chunks.

    This asserts the tool call itself, not just that a review came back.
    An earlier version of this test only checked the final output, which
    let three separate bugs hide at once: provider-native structured
    output made tool calls impossible, an explicit args_schema silently
    broke ToolRuntime injection, and calculate_rating assumed every model
    turn carried structured output. The model reasoned correctly the whole
    time; nothing downstream could tell."""
    integration_rag_manager.index_file(
        integration_repo_data, "services/notifier.py", NOTIFIER_CALLING_BACK_INTO_PROCESSOR_CODE
    )
    agent = CouplingAgent(llm=small_llm, rag_manager=integration_rag_manager)

    raw_result = agent._agent.invoke(
        {"messages": [{"role": "user", "content": REVIEWED_CODE_SUSPECTED_CIRCULAR_DEPENDENCY}]},
        config={"recursion_limit": agent._recursion_limit()},
        context=ReviewContext(repo_id=integration_repo_data.repo_id, owner_id=integration_repo_data.owner_id),
    )
    report_agent_reasoning(raw_result)

    evidence_calls = evidence_tool_calls(raw_result)
    assert evidence_calls != []
    assert evidence_calls[0]["args"]["file_path"] == "services/notifier.py"
    assert raw_result["structured_response"].review[0].incidents != []
