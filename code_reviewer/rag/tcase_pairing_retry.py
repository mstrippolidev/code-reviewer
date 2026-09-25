"""
    Corrective-RAG lookup of a source file's test files in its repo's
    indexed corpus: retrieve, re-rank, judge, and — only when the judge
    confirms nothing — rewrite the query and try exactly once more.
"""
from dataclasses import dataclass

from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.tcase_pairing import PairingCandidate, PairingCandidateFinder
from code_reviewer.rag.tcase_pairing_judge import PairingJudge
from code_reviewer.rag.tcase_pairing_query_rewrite import PairingQueryRewriter
from code_reviewer.rag.tcase_pairing_rerank import PairingReranker
from code_reviewer.schemas.rag.tcase_pairing import PairingMatchStatus, PairingVerdict
from code_reviewer.schemas.submission import SubmittedFile

CONFIRMED_TEST_FILE_CAP = 3


@dataclass(frozen=True)
class PairingCorrectionTools:
    judge: PairingJudge
    query_rewriter: PairingQueryRewriter


@dataclass(frozen=True)
class _AttemptOutcome:
    confirmed: list[SubmittedFile]
    rejection_reasons: list[str]


class CorrectiveTestPairingFinder:
    """Finds up to CONFIRMED_TEST_FILE_CAP judge-confirmed test files for a source file."""

    def __init__(
        self, finder: PairingCandidateFinder, reranker: PairingReranker, correction: PairingCorrectionTools
    ) -> None:
        self._finder = finder
        self._reranker = reranker
        self._correction = correction

    def find_test_files(self, repo_data: RepoData, source_file: SubmittedFile) -> list[SubmittedFile]:
        """Empty when nothing is confirmed even after the one rewritten-query retry.

        Raises:
            VectorStoreQueryError: If a corpus lookup fails.
            ChunkExplanationError: If explaining source_file's code fails.
            PairingJudgeInvocationError: If the judge call fails.
            PairingQueryRewriteError: If the query rewrite fails.
        """
        first_attempt = self._attempt(repo_data, source_file, semantic_query=None)
        if first_attempt.confirmed:
            return first_attempt.confirmed
        rewritten_query = self._correction.query_rewriter.rewrite(source_file, first_attempt.rejection_reasons)
        return self._attempt(repo_data, source_file, semantic_query=rewritten_query).confirmed

    def _attempt(self, repo_data: RepoData, source_file: SubmittedFile, semantic_query: str | None) -> _AttemptOutcome:
        buckets = self._finder.find_candidates(repo_data, source_file, semantic_query)
        survivors = self._reranker.rerank(semantic_query or source_file.content, buckets)
        verdicts = self._correction.judge.judge(source_file, survivors)
        return _AttemptOutcome(
            confirmed=_confirmed_test_files(verdicts, survivors),
            rejection_reasons=[verdict.reasoning for verdict in verdicts if verdict.status != PairingMatchStatus.MATCH],
        )


def _confirmed_test_files(verdicts: list[PairingVerdict], survivors: list[PairingCandidate]) -> list[SubmittedFile]:
    matched = [survivors[verdict.candidate_index] for verdict in verdicts if verdict.status == PairingMatchStatus.MATCH]
    unique_matches = {candidate.file_path: candidate for candidate in matched}
    return [
        SubmittedFile(file_path=candidate.file_path, content=candidate.content)
        for candidate in list(unique_matches.values())[:CONFIRMED_TEST_FILE_CAP]
    ]
