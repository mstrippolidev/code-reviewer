"""
    Tests that the reviewers whose submitted code is treated as data carry the instruction saying so.
"""
import pytest

from code_reviewer.prompts.agents.cohesion import COH_AGENT_SYSTEM_PROMPT
from code_reviewer.prompts.agents.complexity import CMPLX_AGENT_SYSTEM_PROMPT
from code_reviewer.prompts.agents.coupling import COUP_AGENT_REPOLESS_SYSTEM_PROMPT, COUP_AGENT_SYSTEM_PROMPT
from code_reviewer.prompts.agents.solid_1 import SOLID1_AGENT_SYSTEM_PROMPT
from code_reviewer.prompts.agents.solid_2 import SOLID2_AGENT_SYSTEM_PROMPT
from code_reviewer.prompts.agents.testability import TEST_AGENT_SYSTEM_PROMPT
from code_reviewer.prompts.agents.untrusted_code import UNTRUSTED_CODE_INSTRUCTION

PROMPTS = {
    "SOLID1": SOLID1_AGENT_SYSTEM_PROMPT,
    "SOLID2": SOLID2_AGENT_SYSTEM_PROMPT,
    "COH": COH_AGENT_SYSTEM_PROMPT,
    "COUP": COUP_AGENT_SYSTEM_PROMPT,
    "COUP repo-less": COUP_AGENT_REPOLESS_SYSTEM_PROMPT,
    "TEST": TEST_AGENT_SYSTEM_PROMPT,
    "CMPLX": CMPLX_AGENT_SYSTEM_PROMPT,
}


@pytest.mark.parametrize("name", PROMPTS)
def test_the_prompt_tells_the_reviewer_that_submitted_code_is_data(name: str) -> None:
    """Verify the shared instruction is part of the prompt, so removing it from one agent fails here."""
    assert UNTRUSTED_CODE_INSTRUCTION.strip() in PROMPTS[name]
