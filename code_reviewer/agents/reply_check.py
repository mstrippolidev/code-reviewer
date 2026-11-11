"""
    Deterministic checks on one model reply, applied before the agent trusts it.
"""
from dataclasses import dataclass
from enum import Enum

from langchain_core.messages import BaseMessage

from code_reviewer.agents.output_grounding import is_review_invented
from code_reviewer.agents.reasoning import has_reasoning
from code_reviewer.schemas.review import AgentOutput


class ReplyProblem(str, Enum):
    INVENTED = "invented"
    EMPTY_WITHOUT_REASONING = "empty_without_reasoning"


@dataclass(frozen=True)
class AgentReply:
    output: AgentOutput
    messages: list[BaseMessage]


@dataclass(frozen=True)
class ReplyRules:
    checks_quoted_names: bool
    expects_reasoning: bool


def find_reply_problem(reply: AgentReply, code: str, rules: ReplyRules) -> ReplyProblem | None:
    """Why this reply cannot be trusted, or None when it can."""
    if is_review_invented(reply.output, code, rules.checks_quoted_names):
        return ReplyProblem.INVENTED
    if rules.expects_reasoning and _is_empty(reply.output) and not has_reasoning(reply.messages):
        return ReplyProblem.EMPTY_WITHOUT_REASONING
    return None


def _is_empty(output: AgentOutput) -> bool:
    return not any(entry.incidents for entry in output.review)
