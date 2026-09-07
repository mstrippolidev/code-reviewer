"""
    Confirms whether a re-ranked candidate genuinely duplicates the chunk
    under review, seeing both code fragments directly rather than a
    summary. Its verdict is the reported finding itself.
"""
from dataclasses import dataclass
from typing import Protocol

from langchain.agents import create_agent

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.middleware import retry_model, retry_transient_call
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.prompts.rag.dry_judge import DRY_JUDGE_SYSTEM_PROMPT
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
        except Exception as error:
            raise DryJudgeInvocationError("DRY judge failed to review the given candidates.") from error
        return [_as_incident(verdict) for verdict in output.verdicts if verdict.is_duplicate]


def _build_prompt(query_code: str, candidates: list[JudgeCandidate]) -> str:
    candidate_entries = "\n\n".join(
        f"Candidate {index}: {candidate.location}\n{format_snippet(candidate.code)}"
        for index, candidate in enumerate(candidates)
    )
    return f"Chunk under review:\n{format_snippet(query_code)}\n\nCandidates:\n\n{candidate_entries}"


def _as_incident(verdict: DryJudgeVerdict) -> Incident:
    return Incident(
        priority=verdict.priority,
        line_position=verdict.line_position,
        description=verdict.description,
        advice=verdict.advice,
    )
