"""
    Tests for the checks run on one model reply: hand-built replies, no model.
"""
from langchain_core.messages import AIMessage

from code_reviewer.agents.reply_check import AgentReply, ReplyProblem, ReplyRules, find_reply_problem
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, Incident, Priority

CODE = "def total(prices):\n    return sum(prices)\n"
REASONING_MODEL = ReplyRules(checks_quoted_names=True, expects_reasoning=True)
PLAIN_MODEL = ReplyRules(checks_quoted_names=True, expects_reasoning=False)


def output_with(*incidents: Incident) -> AgentOutput:
    return AgentOutput(review=[AgentReviewEntry(code_key=CodeKey.VAR, incidents=list(incidents))])


def real_incident() -> Incident:
    return Incident(priority=Priority.LOW, line_position="1-1", description="`prices` is vague.", advice="rename")


def invented_incident() -> Incident:
    return Incident(priority=Priority.HIGH, line_position="40-41", description="`handle_event` leaks.", advice="fix")


def reasoned() -> list[AIMessage]:
    return [AIMessage(content="answer", additional_kwargs={"reasoning_content": "I read the code."})]


def unreasoned() -> list[AIMessage]:
    return [AIMessage(content="answer")]


def test_an_empty_review_with_no_reasoning_is_a_problem_for_a_reasoning_model() -> None:
    """Verify the failure seen on COUP: nothing found, and the model never reasoned."""
    reply = AgentReply(output_with(), unreasoned())

    assert find_reply_problem(reply, CODE, REASONING_MODEL) is ReplyProblem.EMPTY_WITHOUT_REASONING


def test_an_empty_review_that_was_reasoned_to_is_trusted() -> None:
    """Verify a clean file the model actually thought about is left alone."""
    assert find_reply_problem(AgentReply(output_with(), reasoned()), CODE, REASONING_MODEL) is None


def test_an_empty_review_from_a_model_not_expected_to_reason_is_trusted() -> None:
    """Verify a fast or local model, which sends no reasoning, does not have every clean file retried."""
    assert find_reply_problem(AgentReply(output_with(), unreasoned()), CODE, PLAIN_MODEL) is None


def test_a_review_with_incidents_needs_no_reasoning() -> None:
    """Verify only an empty review is held to the reasoning check."""
    reply = AgentReply(output_with(real_incident()), unreasoned())

    assert find_reply_problem(reply, CODE, REASONING_MODEL) is None


def test_an_invented_review_is_a_problem_whether_or_not_it_reasoned() -> None:
    """Verify the grounding check still runs first and is independent of the reasoning."""
    reply = AgentReply(output_with(invented_incident()), reasoned())

    assert find_reply_problem(reply, CODE, REASONING_MODEL) is ReplyProblem.INVENTED
