"""
    Confirms whether a re-ranked candidate genuinely duplicates the chunk
    under review, seeing both code fragments directly rather than a
    summary. Its verdict is the reported finding itself.
"""
from dataclasses import dataclass
from typing import Protocol

from langchain.agents import create_agent

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.middleware import PRIORITY_DISCOUNTS, retry_model, retry_transient_call
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.pipeline.line_offset import parse_line_range
from code_reviewer.prompts.rag.dry_judge import DRY_JUDGE_SYSTEM_PROMPT
from code_reviewer.rag.disjoint_set import DisjointSet
from code_reviewer.schemas.rag.dry_judge import DryJudgeOutput, DryJudgeVerdict
from code_reviewer.schemas.review import Incident


class DryJudgeInvocationError(Exception):
    """Raised when the DRY judge's LLM call fails or its output cannot be validated."""


class _LocatedChunk(Protocol):
    file_path: str
    chunk_name: str
    start_line: int
    end_line: int


def format_location(chunk: _LocatedChunk, extra: str = "") -> str:
    detail = f", {extra}" if extra else ""
    return f"{chunk.file_path}:{chunk.chunk_name} (lines {chunk.start_line}-{chunk.end_line}{detail})"


def format_snippet(code: str) -> str:
    return f"```\n{code}\n```"


@dataclass
class JudgeCandidate:
    location: str
    code: str


class DryJudgeLike(Protocol):
    def judge(self, query_code: str, candidates: list[JudgeCandidate]) -> list[Incident]: ...


class DryJudge:
    def __init__(self, llm: LLMInterface | None = None) -> None:
        llm = llm or OllamaLLM()
        self._agent = create_agent(
            model=llm.create_raw_model(),
            system_prompt=DRY_JUDGE_SYSTEM_PROMPT,
            middleware=[retry_transient_call, retry_model],
            response_format=llm.build_response_format(DryJudgeOutput),
        )

    def judge(self, query_code: str, candidates: list[JudgeCandidate]) -> list[Incident]:
        """line_position on each returned Incident is relative to
        query_code (starts at 1), the same convention every chunk agent
        already uses — the caller offsets it to file-absolute.

        Raises:
            DryJudgeInvocationError: If the LLM call fails or its output
                cannot be validated against DryJudgeOutput.
        """
        if not candidates:
            return []
        prompt = _build_prompt(query_code, candidates)
        try:
            messages = {"messages": [{"role": "user", "content": prompt}]}
            result = call_with_hard_timeout(lambda: self._agent.invoke(messages))
            output: DryJudgeOutput = result["structured_response"]
            return _incidents_from_verdicts(output.verdicts, candidates)
        except Exception as error:
            raise DryJudgeInvocationError("DRY judge failed to review the given candidates.") from error


def _build_prompt(query_code: str, candidates: list[JudgeCandidate]) -> str:
    candidate_entries = "\n\n".join(
        f"Candidate {index}: {candidate.location}\n{format_snippet(candidate.code)}"
        for index, candidate in enumerate(candidates)
    )
    return f"Chunk under review:\n{format_snippet(query_code)}\n\nCandidates:\n\n{candidate_entries}"


def _incidents_from_verdicts(verdicts: list[DryJudgeVerdict], candidates: list[JudgeCandidate]) -> list[Incident]:
    """Confirmed verdicts whose line_position overlaps become one incident
    — a cluster of candidates duplicating the same range is one finding,
    not one per candidate."""
    confirmed = [verdict for verdict in verdicts if verdict.is_duplicate]
    groups = _group_by_overlapping_range(confirmed)
    return [_incident_for_group(group, candidates) for group in groups]


def _group_by_overlapping_range(verdicts: list[DryJudgeVerdict]) -> list[list[DryJudgeVerdict]]:
    disjoint_set: DisjointSet[int] = DisjointSet()
    for first_index in range(len(verdicts)):
        for second_index in range(first_index + 1, len(verdicts)):
            if _ranges_overlap(verdicts[first_index], verdicts[second_index]):
                disjoint_set.union(first_index, second_index)
    grouped: dict[int, list[DryJudgeVerdict]] = {}
    for index, verdict in enumerate(verdicts):
        grouped.setdefault(disjoint_set.find(index), []).append(verdict)
    return list(grouped.values())


def _ranges_overlap(first: DryJudgeVerdict, second: DryJudgeVerdict) -> bool:
    first_start, first_end = parse_line_range(first.line_position)
    second_start, second_end = parse_line_range(second.line_position)
    return first_start <= second_end and second_start <= first_end


def _incident_for_group(group: list[DryJudgeVerdict], candidates: list[JudgeCandidate]) -> Incident:
    if len(group) == 1:
        return _as_incident(group[0])
    highest = max(group, key=lambda verdict: PRIORITY_DISCOUNTS[verdict.priority])
    locations = ", ".join(candidates[verdict.candidate_index].location for verdict in group)
    return Incident(
        priority=highest.priority,
        line_position=_union_line_position(group),
        description=f"Duplicated across {len(group)} locations: {locations}. {highest.description}",
        advice=highest.advice,
    )


def _union_line_position(group: list[DryJudgeVerdict]) -> str:
    ranges = [parse_line_range(verdict.line_position) for verdict in group]
    return f"{min(start for start, _ in ranges)}-{max(end for _, end in ranges)}"


def _as_incident(verdict: DryJudgeVerdict) -> Incident:
    return Incident(
        priority=verdict.priority,
        line_position=verdict.line_position,
        description=verdict.description,
        advice=verdict.advice,
    )
