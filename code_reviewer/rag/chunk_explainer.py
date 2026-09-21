"""
    Generates a short, embedding-oriented explanation of a code chunk, used
    to strengthen DRY's semantic (Type-4) duplicate search.
"""
from langchain.agents import create_agent

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.middleware import retry_model, retry_transient_call
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.prompts.chunk_explanation import CHUNK_EXPLANATION_SYSTEM_PROMPT
from code_reviewer.rag.errors import ChunkExplanationError
from code_reviewer.schemas.chunk_explanation import ChunkExplanation


class ChunkExplainer:
    """Generates a two-sentence behavioral explanation of a code chunk, via LLM."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        llm = llm or OllamaLLM()
        self._agent = create_agent(
            model=llm.create_raw_model(),
            system_prompt=CHUNK_EXPLANATION_SYSTEM_PROMPT,
            middleware=[retry_transient_call, retry_model],
            response_format=llm.build_response_format(ChunkExplanation),
        )

    def explain(self, code: str) -> str:
        """
        Raises:
            ChunkExplanationError: If the LLM call fails or its output
                cannot be validated against ChunkExplanation.
        """
        try:
            messages = {"messages": [{"role": "user", "content": code}]}
            result = call_with_hard_timeout(lambda: self._agent.invoke(messages))
            output: ChunkExplanation = result["structured_response"]
        except Exception as error:
            raise ChunkExplanationError("Failed to generate a chunk explanation.") from error
        return output.explanation
