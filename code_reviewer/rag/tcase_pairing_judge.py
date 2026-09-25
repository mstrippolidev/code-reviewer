"""
    Confirms which retrieved candidates are really tests of a source file,
    one batched LLM call per set of candidates.
"""
from langchain.agents import create_agent

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.middleware import retry_model, retry_transient_call
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.prompts.rag.tcase_pairing_judge import TCASE_PAIRING_JUDGE_SYSTEM_PROMPT
from code_reviewer.rag.errors import PairingJudgeInvocationError
from code_reviewer.rag.tcase_pairing import PairingCandidate
from code_reviewer.schemas.rag.tcase_pairing import PairingJudgeOutput, PairingVerdict
from code_reviewer.schemas.submission import SubmittedFile


class PairingJudge:
    """Judges each candidate as match, no_match, or ambiguous for one source file."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        llm = llm or OllamaLLM()
        self._agent = create_agent(
            model=llm.create_raw_model(),
            system_prompt=TCASE_PAIRING_JUDGE_SYSTEM_PROMPT,
            middleware=[retry_transient_call, retry_model],
            response_format=llm.build_response_format(PairingJudgeOutput),
        )

    def judge(self, source_file: SubmittedFile, candidates: list[PairingCandidate]) -> list[PairingVerdict]:
        """Returns one verdict per candidate; no LLM call at all when candidates is empty.

        Raises:
            PairingJudgeInvocationError: If the LLM call fails or its output
                cannot be validated against PairingJudgeOutput.
        """
        if not candidates:
            return []
        messages = {"messages": [{"role": "user", "content": _build_prompt(source_file, candidates)}]}
        try:
            result = call_with_hard_timeout(lambda: self._agent.invoke(messages))
            output: PairingJudgeOutput = result["structured_response"]
        except Exception as error:
            raise PairingJudgeInvocationError("Pairing judge failed to review the given candidates.") from error
        return [verdict for verdict in output.verdicts if 0 <= verdict.candidate_index < len(candidates)]


def _build_prompt(source_file: SubmittedFile, candidates: list[PairingCandidate]) -> str:
    candidate_entries = "\n\n".join(
        f"Candidate {index}: {candidate.file_path}\n{candidate.content}"
        for index, candidate in enumerate(candidates)
    )
    return f"SOURCE FILE: {source_file.file_path}\n{source_file.content}\n\nCandidates:\n\n{candidate_entries}"
