"""
    Tests for the CMT agent (comment quality), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
"""
import pytest

from code_reviewer.agents.comments import CommentsAgent
from code_reviewer.schemas.review import CodeKey
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def comments_agent(small_llm) -> CommentsAgent:
    return CommentsAgent(llm=small_llm)


def test_clean_code_is_not_flagged(comments_agent: CommentsAgent) -> None:
    code = load_fixture("shared/clean_service.py")

    result = comments_agent.execute_agent(code, file_path="clean_service.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.CMT
    assert entry.incidents == []
    assert entry.rating == 100


def test_good_comments_are_not_flagged(comments_agent: CommentsAgent) -> None:
    code = load_fixture("comments/good_comments.py")

    result = comments_agent.execute_agent(code, file_path="good_comments.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_redundant_comments_are_flagged(comments_agent: CommentsAgent) -> None:
    code = load_fixture("comments/redundant_comments.py")

    result = comments_agent.execute_agent(code, file_path="redundant_comments.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_stale_ambiguous_comment_is_flagged(comments_agent: CommentsAgent) -> None:
    code = load_fixture("comments/stale_ambiguous_comment.py")

    result = comments_agent.execute_agent(code, file_path="stale_ambiguous_comment.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_commented_out_code_is_flagged(comments_agent: CommentsAgent) -> None:
    code = load_fixture("comments/commented_out_code.py")

    result = comments_agent.execute_agent(code, file_path="commented_out_code.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_implementation_leaking_docstring_is_flagged(comments_agent: CommentsAgent) -> None:
    code = load_fixture("comments/implementation_leaking_docstring.py")

    result = comments_agent.execute_agent(code, file_path="implementation_leaking_docstring.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_file_path_is_stamped_on_every_entry(comments_agent: CommentsAgent) -> None:
    code = load_fixture("comments/redundant_comments.py")

    result = comments_agent.execute_agent(code, file_path="redundant_comments.py")

    assert all(entry.file_path == "redundant_comments.py" for entry in result.review)
