"""
    Concrete class for the DRY agent: duplication within this PR and
    against the repo's indexed history.
"""

from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.dry import DRY_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class DryAgent(AgentBase):
    """Reviews duplication evidence assembled upstream (rag/dry_evidence.py,
    called from pipeline/dispatch.py) — never raw file content, since a
    duplication judgment needs the other location's code, not just this
    file in isolation."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.DRY, DRY_AGENT_SYSTEM_PROMPT, llm)
