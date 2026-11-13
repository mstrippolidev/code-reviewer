"""
    Picks which files of a finished review are worth putting to the exemplar judge panel.
"""
from code_reviewer.prompts.exemplar_promotion import PRINCIPLE_STATEMENTS
from code_reviewer.schemas.review import CodeKey

PERFECT_RATING = 100


def perfect_file_nominations(agent_entries: dict[str, dict[str, dict]]) -> list[tuple[str, CodeKey]]:
    """The (file, agent) pairs where an agent that has promotion criteria rated the whole file 100.

    Takes a review's stored `agent_entries` (file path, then code key, then the dumped entry).
    A failed or skipped entry carries no judgment, so it never nominates.
    """
    nominations = []
    for file_path, entries_by_agent in agent_entries.items():
        for code_key_value, entry in entries_by_agent.items():
            code_key = CodeKey(code_key_value)
            if code_key in PRINCIPLE_STATEMENTS and _is_perfect(entry):
                nominations.append((file_path, code_key))
    return nominations


def _is_perfect(entry: dict) -> bool:
    return entry["rating"] == PERFECT_RATING and not entry.get("failed") and not entry.get("skipped")
