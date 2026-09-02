"""
    Promotion of reviewed code into the exemplar corpus, gated by a judge
    panel rather than by the review score that nominated it.
"""
import logging
from dataclasses import dataclass
from enum import Enum

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.consensus.vote import Vote, VoteResult
from code_reviewer.prompts.exemplar_promotion import build_promotion_prompt
from code_reviewer.rag.exemplars import ExemplarSource, ExemplarStore
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import CodeKey

logger = logging.getLogger(__name__)


class PromotionOutcome(Enum):
    """What a judge panel decided about one candidate.

    Three outcomes rather than two: a split panel and a unanimous rejection
    are different signals, and which of them deserves a human's attention is
    a policy question for the caller, not one this module answers.
    """

    PROMOTED = "promoted"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class ExemplarCandidate:
    """One reviewed chunk queued for possible promotion."""

    repo_data: RepoData
    code_key: CodeKey
    source: ExemplarSource


class ExemplarPromoter:
    """Decides whether one reviewed chunk earns a place in the exemplar corpus."""

    def __init__(
        self,
        store: ExemplarStore,
        voters: list[LLMInterface],
        vote: Vote | None = None,
    ) -> None:
        self._store = store
        self._voters = voters
        self._vote = vote or Vote()

    def promote(self, candidate: ExemplarCandidate) -> PromotionOutcome:
        """Put one candidate to the judge panel, storing it only on a
        unanimous yes.

        The review score that nominated this candidate is deliberately not
        given to the judges: it is the thing being second-guessed, and a
        panel told the code already scored 100 would be agreeing with the
        agent rather than checking it.

        Returns:
            What the panel decided. Only PROMOTED has written anything.

        Raises:
            UnsupportedExemplarPrincipleError: If no agent retrieves
                exemplars for this candidate's principle.
            ConsensusVoteError: If any judge fails to return a verdict.
            RepoOwnerRequiredError: If the candidate's repo has no owner_id.
            FileEmbeddingError: If splitting or embedding the code fails.
            VectorStoreWriteError: If the write itself fails.
        """
        prompt = build_promotion_prompt(candidate.code_key)
        outcome = self._decide(self._vote.vote_multi_provider(prompt, candidate.source.code, self._voters))
        if outcome is PromotionOutcome.PROMOTED:
            self._store.add_exemplar(candidate.repo_data, candidate.code_key, candidate.source)
        logger.info(
            "Exemplar candidate %s (%s) -> %s",
            candidate.source.file_path,
            candidate.code_key.value,
            outcome.value,
        )
        return outcome

    def _decide(self, result: VoteResult) -> PromotionOutcome:
        if not result.unanimous:
            return PromotionOutcome.NEEDS_REVIEW
        return PromotionOutcome.PROMOTED if result.votes[0].verdict else PromotionOutcome.REJECTED
