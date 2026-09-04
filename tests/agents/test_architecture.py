"""
    Tests for the ARCH agent (architecture). Content-based checks run
    against a real small local model, per this project's approach to
    LLM-backed tests. The hard-limit short-circuit test needs no LLM at
    all — ARCH is a FileSizeAwareAgentBase agent, same as SOLID2/COH/COUP,
    so it isn't marked with pytest.mark.llm like the rest of this file.
"""
from unittest.mock import Mock

import pytest

from code_reviewer.agents.architecture import ArchitectureAgent
from code_reviewer.agents.base import FileReviewMeta, ReviewContext
from code_reviewer.agents.cross_file_evidence_tool import GetFileChunksTool
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import CodeKey, Priority, SizeStatus
from tests.agents.conftest import evidence_tool_calls, report_agent_reasoning
from tests.helpers import load_fixture


@pytest.fixture
def arch_agent(small_llm) -> ArchitectureAgent:
    return ArchitectureAgent(llm=small_llm)


@pytest.mark.llm
def test_good_architecture_is_not_flagged(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/good_architecture.py")

    result = arch_agent.execute_agent(code, file_path="good_architecture.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.ARCH
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_layer_violation_is_flagged(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/layer_violation.py")

    result = arch_agent.execute_agent(code, file_path="layer_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_dependency_direction_violation_is_flagged(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/dependency_direction_violation.py")

    result = arch_agent.execute_agent(code, file_path="dependency_direction_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_construction_mixed_with_use_violation_is_flagged(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/construction_mixed_with_use_violation.py")

    result = arch_agent.execute_agent(code, file_path="construction_mixed_with_use_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_pattern_inconsistency_violation_is_flagged(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/pattern_inconsistency_violation.py")

    result = arch_agent.execute_agent(code, file_path="pattern_inconsistency_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_file_path_is_stamped_on_every_entry(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/layer_violation.py")

    result = arch_agent.execute_agent(code, file_path="layer_violation.py")

    assert all(entry.file_path == "layer_violation.py" for entry in result.review)


@pytest.mark.llm
def test_high_priority_scenario_is_flagged_high(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/priority_high.py")

    result = arch_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


@pytest.mark.llm
def test_medium_priority_scenario_is_flagged_medium(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/priority_medium.py")

    result = arch_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


@pytest.mark.llm
def test_low_priority_scenario_is_flagged_low(arch_agent: ArchitectureAgent) -> None:
    code = load_fixture("arch/priority_low.py")

    result = arch_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_out_of_scope_scenario_is_flagged_low(arch_agent: ArchitectureAgent) -> None:
    """A business rule duplicated across two layers (request handler and
    domain object both enforcing the same minimum) is architecture-
    adjacent but outside ARCH's four in-scope categories, so it must
    still be reported, but only at priority low."""
    code = load_fixture("arch/priority_out_of_scope_low.py")

    result = arch_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_injected_abstraction_is_not_flagged_as_layer_violation(arch_agent: ArchitectureAgent) -> None:
    """A domain policy that only touches infrastructure through a
    Protocol handed to its constructor must not be mistaken for a class
    reaching for infrastructure itself."""
    code = load_fixture("arch/false_positive_injected_abstraction.py")

    result = arch_agent.execute_agent(code, file_path="false_positive_injected_abstraction.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_infrastructure_adapter_is_not_flagged(arch_agent: ArchitectureAgent) -> None:
    """A repository class whose entire declared job is talking to a
    database is the correct home for SQL, not a layering violation."""
    code = load_fixture("arch/false_positive_infrastructure_adapter.py")

    result = arch_agent.execute_agent(code, file_path="false_positive_infrastructure_adapter.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_template_method_is_not_flagged_as_wrong_direction(arch_agent: ArchitectureAgent) -> None:
    """A base class calling its own abstract method, overridden by a
    subclass, points the dependency the right way and must not be
    mistaken for the general depending on the specific."""
    code = load_fixture("arch/false_positive_template_method.py")

    result = arch_agent.execute_agent(code, file_path="false_positive_template_method.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_factory_function_is_not_flagged_as_construction_mixed_with_use(arch_agent: ArchitectureAgent) -> None:
    """A function whose sole declared purpose is assembling an object
    graph is exactly where construction belongs, not a violation."""
    code = load_fixture("arch/false_positive_factory_function.py")

    result = arch_agent.execute_agent(code, file_path="false_positive_factory_function.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_value_object_construction_is_not_flagged(arch_agent: ArchitectureAgent) -> None:
    """Building a small immutable value object inline as logic computes
    is not the same as assembling an infrastructure collaborator."""
    code = load_fixture("arch/false_positive_value_object_construction.py")

    result = arch_agent.execute_agent(code, file_path="false_positive_value_object_construction.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_naturally_varying_shapes_are_not_flagged_as_inconsistent(arch_agent: ArchitectureAgent) -> None:
    """Methods returning different shapes because the operations
    themselves genuinely differ (single lookup, bulk query, count) must
    not be mistaken for a missing convention."""
    code = load_fixture("arch/false_positive_naturally_varying_shapes.py")

    result = arch_agent.execute_agent(code, file_path="false_positive_naturally_varying_shapes.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_hard_limit_exceeded_short_circuits_without_an_llm_call(arch_agent: ArchitectureAgent) -> None:
    code = "x\n" * 900

    result = arch_agent.execute_agent(
        code, file_path="huge_file.py", review_meta=FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED)
    )

    entry = result.review[0]
    assert entry.rating == 0
    assert entry.code_key == CodeKey.ARCH
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-900"


def test_normal_size_status_does_not_short_circuit(arch_agent: ArchitectureAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = {}

    def fake_invoke(self, code: str, repo_data=None):
        invoked["called"] = True
        raise AssertionError("stop before a real LLM call")

    monkeypatch.setattr(ArchitectureAgent, "_invoke", fake_invoke)

    with pytest.raises(AssertionError, match="stop before a real LLM call"):
        arch_agent.execute_agent(
            "x = 1", file_path="tiny.py", review_meta=FileReviewMeta(size_status=SizeStatus.NORMAL)
        )

    assert invoked["called"] is True


def test_without_rag_manager_no_tool_is_wired(small_llm) -> None:
    """Verify an ARCH agent built with no rag_manager (e.g. a standalone
    file review, or an existing test/caller unaware of this feature)
    behaves exactly as before — no tool, no context schema."""
    agent = ArchitectureAgent(llm=small_llm)

    assert agent._build_tools() is None
    assert agent._context_schema() is None
    assert agent._recursion_limit() == 4


def test_with_rag_manager_the_evidence_tool_is_wired(small_llm) -> None:
    """Verify an ARCH agent built with a rag_manager gets the evidence
    tool, a matching context schema, and extra recursion headroom for
    the tool round-trip."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    agent = ArchitectureAgent(llm=small_llm, rag_manager=rag_manager)

    tools = agent._build_tools()

    assert len(tools) == 1
    assert isinstance(tools[0], GetFileChunksTool)
    assert tools[0].rag_manager is rag_manager
    assert agent._context_schema() is ReviewContext
    assert agent._recursion_limit() > 4


# --- Real end-to-end: real Postgres/pgvector, real Ollama embeddings, and
# a real chat LLM (--llm-provider openrouter to run against OpenRouter).

INFRASTRUCTURE_REGISTRY_CODE = (
    "def lookup(rule_name):\n"
    "    connection = psycopg2.connect(DATABASE_URL)\n"
    "    cursor = connection.cursor()\n"
    '    cursor.execute("SELECT config FROM rules WHERE name = %s", (rule_name,))\n'
    "    return cursor.fetchone()\n"
)

DOMAIN_RULE_IMPORTING_AMBIGUOUS_NAME = (
    "from platform_registry import lookup\n\n\n"
    "class PricingRule:\n"
    "    def discount_for(self, customer):\n"
    "        config = lookup('premium_discount')\n"
    "        if customer.is_premium:\n"
    "            return config['rate']\n"
    "        return 0\n"
)


@pytest.mark.db
@pytest.mark.llm
def test_real_arch_calls_the_evidence_tool_for_an_ambiguous_import(
    integration_rag_manager: LlamaIndexRagManager,
    integration_repo_data: RepoData,
    small_llm: LLMInterface,
) -> None:
    """Full loop, real model: PricingRule is a domain unit calling
    lookup() from a module whose name gives nothing away — whether that's
    a layering violation depends entirely on whether lookup touches
    infrastructure, which this file cannot show. The agent has to fetch it.

    Asserts the tool call itself, not just the final review: a review that
    merely looks right can still have been produced by guessing, which is
    exactly what happened here before ToolStrategy replaced the provider's
    native structured output."""
    integration_rag_manager.index_file(
        integration_repo_data, "platform_registry.py", INFRASTRUCTURE_REGISTRY_CODE
    )
    agent = ArchitectureAgent(llm=small_llm, rag_manager=integration_rag_manager)

    raw_result = agent._agent.invoke(
        {"messages": [{"role": "user", "content": DOMAIN_RULE_IMPORTING_AMBIGUOUS_NAME}]},
        config={"recursion_limit": agent._recursion_limit()},
        context=ReviewContext(repo_id=integration_repo_data.repo_id, owner_id=integration_repo_data.owner_id),
    )
    report_agent_reasoning(raw_result)

    assert evidence_tool_calls(raw_result) != []
    assert raw_result["structured_response"].review[0].incidents != []
