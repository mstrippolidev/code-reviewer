"""
    Generates a short, embedding-oriented explanation of a code chunk, used
    to strengthen DRY's semantic (Type-4) duplicate search.
"""
from langchain_core.prompts import ChatPromptTemplate

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.prompts.chunk_explanation import CHUNK_EXPLANATION_SYSTEM_PROMPT
from code_reviewer.rag.errors import ChunkExplanationError
from code_reviewer.schemas.chunk_explanation import ChunkExplanation


class ChunkExplainer:
    """Generates a two-sentence behavioral explanation of a code chunk, via LLM."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        llm_factory = llm if llm is not None else OllamaLLM()
        self._model = llm_factory.create_model(ChunkExplanation)

    def explain(self, code: str) -> str:
        """
        Raises:
            ChunkExplanationError: If the LLM call fails or its output
                cannot be validated against ChunkExplanation.
        """
        chunk_explanation_chat = ChatPromptTemplate(
            [("system", CHUNK_EXPLANATION_SYSTEM_PROMPT), ("human", "{code}")]
        )
        chain = chunk_explanation_chat | self._model
        try:
            result = chain.invoke({"code": code})
        except Exception as error:
            raise ChunkExplanationError("Failed to generate a chunk explanation.") from error
        return result.explanation
