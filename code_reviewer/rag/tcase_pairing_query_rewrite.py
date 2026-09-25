"""
    Rewrites the TCASE pairing search query after a first attempt confirmed
    no test file, using the judge's own rejection reasons as feedback.
"""
from langchain.agents import create_agent

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.middleware import retry_model, retry_transient_call
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.prompts.rag.tcase_pairing_rewrite import TCASE_PAIRING_REWRITE_SYSTEM_PROMPT
from code_reviewer.rag.errors import PairingQueryRewriteError
from code_reviewer.schemas.rag.tcase_pairing import PairingQueryRewriteOutput
from code_reviewer.schemas.submission import SubmittedFile

_NOTHING_FOUND = "The first search found no candidate test files at all."


class PairingQueryRewriter:
    """Produces a new natural-language search query for a source file's test file."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        llm = llm or OllamaLLM()
        self._agent = create_agent(
            model=llm.create_raw_model(),
            system_prompt=TCASE_PAIRING_REWRITE_SYSTEM_PROMPT,
            middleware=[retry_transient_call, retry_model],
            response_format=llm.build_response_format(PairingQueryRewriteOutput),
        )

    def rewrite(self, source_file: SubmittedFile, rejection_reasons: list[str]) -> str:
        """
        Args:
            rejection_reasons: The judge's reasoning for each candidate it
                did not confirm; empty when the first search found nothing.

        Raises:
            PairingQueryRewriteError: If the LLM call fails or its output
                cannot be validated against PairingQueryRewriteOutput.
        """
        messages = {"messages": [{"role": "user", "content": _build_prompt(source_file, rejection_reasons)}]}
        try:
            result = call_with_hard_timeout(lambda: self._agent.invoke(messages))
            output: PairingQueryRewriteOutput = result["structured_response"]
        except Exception as error:
            raise PairingQueryRewriteError("Failed to rewrite the test-file search query.") from error
        return output.query


def _build_prompt(source_file: SubmittedFile, rejection_reasons: list[str]) -> str:
    reasons = "\n".join(f"- {reason}" for reason in rejection_reasons) or _NOTHING_FOUND
    return f"SOURCE FILE: {source_file.file_path}\n{source_file.content}\n\nRejected candidates:\n{reasons}"
