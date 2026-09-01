"""
    Middleware that puts an agent's critical findings to a judge panel and
    downgrades the ones the panel does not unanimously uphold.
"""
import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState, Runtime
from langchain_core.messages import AnyMessage, HumanMessage

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.config.settings import get_settings
from code_reviewer.consensus.vote import ConsensusVoteError, Vote
from code_reviewer.prompts.critical_confirmation import CRITICAL_CONFIRMATION_PROMPTS
from code_reviewer.schemas.review import CodeKey, Incident, Priority

logger = logging.getLogger(__name__)


class CriticalConfirmationError(Exception):
    """Raised when a critical finding cannot be traced back to the code that produced it."""


class CriticalConfirmation(AgentMiddleware):
    """Downgrades a critical finding to high unless a panel of independent
    judges unanimously upholds it."""

    def __init__(self, code_key: CodeKey, judges: list[LLMInterface] | None = None) -> None:
        super().__init__()
        self._code_key = code_key
        self._judges = judges

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        output = state.get("structured_response")
        confirmation_prompt = CRITICAL_CONFIRMATION_PROMPTS.get(self._code_key)
        if output is None or confirmation_prompt is None:
            return None
        judges = self._panel()
        if not judges:
            return None
        reviewed_code = _code_under_review(state["messages"])
        for review in output.review:
            self._downgrade_unconfirmed(review.incidents, reviewed_code, confirmation_prompt)
        return {"structured_response": output}

    def _panel(self) -> list[LLMInterface]:
        if self._judges is not None:
            return self._judges
        return [OpenRouter(model_name=model) for model in get_settings().critical_confirmation_panel()]

    def _downgrade_unconfirmed(
        self, incidents: list[Incident], reviewed_code: str, confirmation_prompt: str
    ) -> None:
        for incident in incidents:
            if incident.priority != Priority.CRITICAL:
                continue
            if not self._is_confirmed(incident, reviewed_code, confirmation_prompt):
                logger.info("Downgrading unconfirmed critical at %s.", incident.line_position)
                incident.priority = Priority.HIGH

    def _is_confirmed(
        self, incident: Incident, reviewed_code: str, confirmation_prompt: str
    ) -> bool:
        try:
            result = Vote().vote_multi_provider(
                confirmation_prompt, _describe_finding(incident, reviewed_code), self._panel()
            )
        except ConsensusVoteError:
            logger.warning("Critical confirmation did not complete; downgrading the finding.")
            return False
        return result.unanimous and result.votes[0].verdict


def _code_under_review(messages: list[AnyMessage]) -> str:
    """The agent's original request — a whole file or one chunk, depending on
    the agent, so the judge sees what the reviewer saw. Later human messages
    are retry_model's corrections."""
    for message in messages:
        if isinstance(message, HumanMessage):
            return str(message.content)
    raise CriticalConfirmationError("No reviewed code found in the agent's messages.")


def _describe_finding(incident: Incident, reviewed_code: str) -> str:
    return (
        f"Finding flagged as critical, at lines {incident.line_position}:\n"
        f"{incident.description}\n\n"
        f"Code under review:\n{reviewed_code}"
    )
