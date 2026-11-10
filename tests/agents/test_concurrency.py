"""
    Tests for the CONC agent (concurrency safety), run against a real
    small model rather than a mock, per this project's approach to
    LLM-backed tests. CONC is a plain AgentBase chunk agent, so there's no
    hard-limit short-circuit to test here, unlike the FileSizeAwareAgentBase
    file agents (SOLID2, COH, COUP). What each fixture should produce lives
    in tests/fixtures/conc/labels.json and is checked in
    test_agent_labels.py.
"""
import pytest

from code_reviewer.agents.concurrency import ConcurrencyAgent
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def conc_agent(small_llm) -> ConcurrencyAgent:
    return ConcurrencyAgent(llm=small_llm)


def test_file_path_is_stamped_on_every_entry(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/unprotected_shared_state_violation.py")

    result = conc_agent.execute_agent(code, file_path="unprotected_shared_state_violation.py")

    assert all(entry.file_path == "unprotected_shared_state_violation.py" for entry in result.review)
