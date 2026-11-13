"""
    Tests for choosing which files of a finished review are nominated as exemplars.
"""
from api.exemplars.candidates import perfect_file_nominations
from code_reviewer.schemas.review import CodeKey


def test_a_perfect_rating_from_an_agent_with_promotion_criteria_is_nominated() -> None:
    """Verify the whole file is nominated for the agent that rated it 100."""
    entries = {"a.py": {"SOLID1": {"rating": 100}, "COH": {"rating": 100}}}

    assert perfect_file_nominations(entries) == [("a.py", CodeKey.SOLID1), ("a.py", CodeKey.COH)]


def test_an_imperfect_rating_is_not_nominated() -> None:
    """Verify only a 100 nominates: anything lower means the agent found a problem."""
    assert perfect_file_nominations({"a.py": {"SOLID1": {"rating": 99}}}) == []


def test_an_agent_without_promotion_criteria_is_not_nominated() -> None:
    """Verify agents that never read exemplars cannot fill the corpus."""
    assert perfect_file_nominations({"a.py": {"VAR": {"rating": 100}}}) == []


def test_a_failed_or_skipped_entry_is_not_nominated() -> None:
    """Verify an entry that carries no judgment cannot nominate, even at the default rating of 100."""
    entries = {"a.py": {"SOLID1": {"rating": 100, "failed": True}, "COUP": {"rating": 100, "skipped": True}}}

    assert perfect_file_nominations(entries) == []
