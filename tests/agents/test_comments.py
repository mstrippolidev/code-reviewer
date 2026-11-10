"""
    Tests for the CMT agent (comment quality), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
    What each fixture should produce lives in
    tests/fixtures/comments/labels.json and is checked in test_agent_labels.py.
"""
import pytest

from code_reviewer.agents.comments import CommentsAgent
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def comments_agent(small_llm) -> CommentsAgent:
    return CommentsAgent(llm=small_llm)


def test_file_path_is_stamped_on_every_entry(comments_agent: CommentsAgent) -> None:
    code = load_fixture("comments/redundant_comments.py")

    result = comments_agent.execute_agent(code, file_path="redundant_comments.py")

    assert all(entry.file_path == "redundant_comments.py" for entry in result.review)
