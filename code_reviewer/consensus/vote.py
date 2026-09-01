"""
    Shared consensus-voting primitive: run the same yes/no judgment across a
    caller-supplied list of voters and report whether they agreed.
"""
import logging
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain_core.runnables import RunnableLambda, RunnableParallel
from pydantic import BaseModel, Field

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.middleware import retry_model

logger = logging.getLogger(__name__)


class ConsensusVoteError(Exception):
    """Raised when any voter fails to produce a verdict."""


class VoteVerdict(BaseModel):
    reasoning: str = Field(
        description="One sentence weighing the evidence for and against, written before the verdict."
    )
    verdict: bool = Field(description="True if the posed question holds, False otherwise.")


@dataclass(frozen=True)
class VoteResult:
    """Every voter's verdict on one question. Not itself an LLM-facing
    schema, so a plain dataclass rather than a Pydantic model."""

    votes: list[VoteVerdict]

    @property
    def unanimous(self) -> bool:
        """True when every voter reached the same verdict."""
        return len({vote.verdict for vote in self.votes}) == 1


class Vote:
    """Runs one consensus vote across a caller-supplied list of voters.

    Both public methods delegate to the same private mechanism — config A
    and config B differ only in how the caller builds the voters list
    (distinct providers vs. one provider sampled repeatedly at a raised
    temperature), never in how a vote is run or aggregated. Vote itself
    knows nothing about either caller's providers or temperatures.
    """

    def vote_multi_provider(
        self, system_prompt: str, content: str, voters: list[LLMInterface]
    ) -> VoteResult:
        """Config A: distinct-provider voters, for a decision whose blast
        radius justifies genuine independence (e.g. exemplar promotion).

        Args:
            system_prompt: The question every voter judges against.
            content: The candidate under judgment, sent verbatim to every voter.
            voters: Independently configured providers, one call each.

        Returns:
            Every voter's verdict, plus whether they agreed.

        Raises:
            ConsensusVoteError: If any voter fails to produce a verdict.
        """
        return self._run(system_prompt, content, voters)

    def _run(self, system_prompt: str, content: str, voters: list[LLMInterface]) -> VoteResult:
        """Runs every voter concurrently via a single RunnableParallel fan-out."""
        branches = {str(index): self._voter_branch(system_prompt, voter) for index, voter in enumerate(voters)}
        try:
            results = RunnableParallel(branches).invoke(content)
        except Exception as error:
            logger.error("A consensus voter failed to produce a verdict.")
            raise ConsensusVoteError("A consensus voter failed to produce a verdict.") from error
        return VoteResult(votes=[results[key] for key in sorted(results, key=int)])

    def _voter_branch(self, system_prompt: str, voter: LLMInterface) -> RunnableLambda:
        """Builds a branch that runs one voter's structured-output call
        against the shared question and content."""
        agent = create_agent(
            model=voter.create_raw_model(),
            system_prompt=system_prompt,
            middleware=[retry_model],
            response_format=voter.build_response_format(VoteVerdict),
        )
        return RunnableLambda(
            lambda text: agent.invoke({"messages": [{"role": "user", "content": text}]})["structured_response"]
        )
