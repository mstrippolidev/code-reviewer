"""
    Wraps a DryJudge so an oversized query/candidate pair never reaches it
    whole: the larger side is split into overlapping pieces, each piece is
    judged independently against the untouched side, and the results are
    merged by union rather than a vote.
"""
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from code_reviewer.pipeline.line_offset import offset_incidents
from code_reviewer.rag.dry_judge import DryJudgeLike, JudgeCandidate
from code_reviewer.schemas.review import Incident, Priority

_MAX_SPLIT_DEPTH = 2

_UNREVIEWED_ADVICE = "Manually compare this chunk against the flagged candidate for duplicated logic."


@dataclass(frozen=True)
class SplitConfig:
    max_pair_chars: int
    overlap_chars: int


class SizeGuardedDryJudge:
    """Same judge(query_code, candidates) contract as DryJudge, safe to
    call regardless of input size."""

    def __init__(self, dry_judge: DryJudgeLike, config: SplitConfig) -> None:
        self._dry_judge = dry_judge
        self._config = config

    def judge(self, query_code: str, candidates: list[JudgeCandidate]) -> list[Incident]:
        safe, oversized = self._partition(query_code, candidates)
        incidents = self._dry_judge.judge(query_code, safe) if safe else []
        for candidate in oversized:
            incidents += self._judge_pair(query_code, candidate, depth=0)
        return incidents

    def _partition(
        self, query_code: str, candidates: list[JudgeCandidate]
    ) -> tuple[list[JudgeCandidate], list[JudgeCandidate]]:
        safe, oversized = [], []
        for candidate in candidates:
            bucket = oversized if self._is_oversized(query_code, candidate) else safe
            bucket.append(candidate)
        return safe, oversized

    def _is_oversized(self, query_code: str, candidate: JudgeCandidate) -> bool:
        return len(query_code) > self._config.max_pair_chars or len(candidate.code) > self._config.max_pair_chars

    def _judge_pair(self, query_code: str, candidate: JudgeCandidate, depth: int) -> list[Incident]:
        if not self._is_oversized(query_code, candidate):
            return self._dry_judge.judge(query_code, [candidate])
        if depth >= _MAX_SPLIT_DEPTH:
            return [_unreviewed_incident(query_code, candidate)]
        if len(query_code) > self._config.max_pair_chars:
            return self._split_query_and_judge(query_code, candidate, depth)
        return self._split_candidate_and_judge(query_code, candidate, depth)

    def _split_query_and_judge(self, query_code: str, candidate: JudgeCandidate, depth: int) -> list[Incident]:
        incidents = []
        for piece, start_line in self._split(query_code):
            incidents += offset_incidents(self._judge_pair(piece, candidate, depth + 1), start_line)
        return incidents

    def _split_candidate_and_judge(self, query_code: str, candidate: JudgeCandidate, depth: int) -> list[Incident]:
        # A verdict's line_position is always relative to query_code (see
        # DryJudge.judge), so splitting the candidate side needs no offset.
        incidents = []
        for piece, _ in self._split(candidate.code):
            incidents += self._judge_pair(query_code, JudgeCandidate(candidate.location, piece), depth + 1)
        return incidents

    def _split(self, code: str) -> list[tuple[str, int]]:
        # Halves the text itself rather than using max_pair_chars as the
        # chunk size — otherwise content far larger than the threshold
        # explodes into dozens of pieces per level instead of ~2 halves,
        # and the depth cap no longer bounds the total call count.
        chunk_size = len(code) // 2 + self._config.overlap_chars
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=self._config.overlap_chars,
            add_start_index=True,
        )
        pieces = []
        for document in splitter.create_documents([code]):
            start_line = _line_number_at(code, document.metadata["start_index"])
            pieces.append((document.page_content, start_line))
        return pieces


def _line_number_at(text: str, char_index: int) -> int:
    return text.count("\n", 0, char_index) + 1


def _unreviewed_incident(query_code: str, candidate: JudgeCandidate) -> Incident:
    last_line = query_code.count("\n") + 1
    return Incident(
        priority=Priority.LOW,
        line_position=f"1-{last_line}",
        description=f"{candidate.location} stayed too large to judge for duplication even after splitting.",
        advice=_UNREVIEWED_ADVICE,
    )
