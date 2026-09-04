"""
    Builds DRY's final AgentReviewEntry for one file: templates every
    exact structural-hash match directly, and asks the DRY judge to
    confirm the fuzzy, re-ranked candidates a search only guessed at.
"""
from code_reviewer.agents.llm.middleware import rating_from_incidents
from code_reviewer.pipeline.line_offset import offset_incidents
from code_reviewer.rag.dry_evidence import extract_snippet
from code_reviewer.rag.dry_judge import DryJudge, JudgeCandidate, format_location
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralMatch
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, Incident, Priority

_EXTRACT_ADVICE = "Extract the shared logic into one function or method and have every location call it."

# A hash match proves identical structure, not identical intent — below
# this many lines, treat the match as coincidental rather than a duplicate.
_MIN_TEMPLATED_MATCH_LINES = 3


def build_dry_review_entry(
    file_path: str,
    file_content: str,
    intra_pr_groups: list[list[LocatedChunk]],
    history_matches: list[ChunkHistoryMatch],
    dry_judge: DryJudge,
) -> AgentReviewEntry:
    incidents = _templated_intra_pr_incidents(file_path, intra_pr_groups)
    incidents += _templated_history_structural_incidents(history_matches)
    incidents += _judged_incidents(file_content, history_matches, dry_judge)
    return AgentReviewEntry(
        file_path=file_path, code_key=CodeKey.DRY, incidents=incidents, rating=rating_from_incidents(incidents)
    )


def _templated_intra_pr_incidents(file_path: str, groups: list[list[LocatedChunk]]) -> list[Incident]:
    incidents = []
    for group in groups:
        for member in group:
            if member.match.file_path != file_path or _is_trivial(member.match):
                continue
            other_locations = [other.match for other in group if other is not member]
            incidents.append(_exact_match_incident(member.match, other_locations))
    return incidents


def _templated_history_structural_incidents(history_matches: list[ChunkHistoryMatch]) -> list[Incident]:
    return [
        _exact_match_incident(match.chunk, match.structural_matches)
        for match in history_matches
        if match.structural_matches and not _is_trivial(match.chunk)
    ]


def _is_trivial(match: StructuralMatch) -> bool:
    return match.end_line - match.start_line + 1 < _MIN_TEMPLATED_MATCH_LINES


def _exact_match_incident(own: StructuralMatch, duplicates_of: list[StructuralMatch]) -> Incident:
    locations = ", ".join(format_location(other) for other in duplicates_of)
    return Incident(
        # critical requires judging a security/money-path context a hash
        # match alone can't assess, so a templated exact match is always high.
        priority=Priority.HIGH,
        line_position=f"{own.start_line}-{own.end_line}",
        description=f"{own.chunk_name} is structurally identical to {locations}.",
        advice=_EXTRACT_ADVICE,
    )


def _judged_incidents(file_content: str, history_matches: list[ChunkHistoryMatch], dry_judge: DryJudge) -> list[Incident]:
    incidents = []
    for match in history_matches:
        candidates = _fuzzy_candidates(match)
        if not candidates:
            continue
        query_code = extract_snippet(file_content, match.chunk)
        confirmed = dry_judge.judge(query_code, candidates)
        incidents += offset_incidents(confirmed, match.chunk.start_line)
    return incidents


def _fuzzy_candidates(match: ChunkHistoryMatch) -> list[JudgeCandidate]:
    """Deduplicated by location: the same location surviving more than one
    search route is stronger evidence, not a second thing to ask about."""
    seen: dict[tuple[str, str, int, int], JudgeCandidate] = {}
    for bucket in (match.semantic_matches, match.code_matches, match.lexical_matches):
        for candidate in bucket:
            key = (candidate.file_path, candidate.chunk_name, candidate.start_line, candidate.end_line)
            seen.setdefault(key, JudgeCandidate(location=format_location(candidate), code=candidate.code))
    return list(seen.values())
