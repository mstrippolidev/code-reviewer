"""
    The jury that decides which retrieved exemplars are shown to an agent: several
    models judge every candidate, and only a candidate all of them call relevant is kept.
"""
import contextvars
from concurrent.futures import ThreadPoolExecutor

from langchain.agents import create_agent

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.call_observer import build_model_call_observer
from code_reviewer.agents.llm.llm_caller import LlmCaller
from code_reviewer.agents.llm.middleware import retry_model, retry_transient_call
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.prompts.rag.exemplar_judge import EXEMPLAR_JUDGE_SYSTEM_PROMPT, PRINCIPLE_FOCUS
from code_reviewer.rag.errors import ExemplarJudgeInvocationError
from code_reviewer.rag.exemplars import Exemplar
from code_reviewer.schemas.rag.exemplar_judge import ExemplarJudgeOutput, ExemplarRelevance
from code_reviewer.schemas.review import CodeKey
from code_reviewer.telemetry.rag_metrics import rag_metrics


class ExemplarJudge:
    """One model's opinion on which candidates are good references for the code under review."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        llm = llm or OllamaLLM()
        self._agent = create_agent(
            model=llm.create_raw_model(),
            system_prompt=EXEMPLAR_JUDGE_SYSTEM_PROMPT,
            middleware=[
                retry_transient_call,
                retry_model,
                build_model_call_observer(LlmCaller.EXEMPLAR_JUDGE.value, llm.model_name),
            ],
            response_format=llm.build_response_format(ExemplarJudgeOutput),
        )

    def pick_relevant(self, code_key: CodeKey, code: str, candidates: list[Exemplar]) -> list[Exemplar]:
        """The candidates this model calls relevant, in the order given; one it skips counts as not relevant.

        Raises:
            ExemplarJudgeInvocationError: If the LLM call fails or its output
                cannot be validated against ExemplarJudgeOutput.
        """
        messages = {"messages": [{"role": "user", "content": _build_prompt(code_key, code, candidates)}]}
        try:
            result = call_with_hard_timeout(lambda: self._agent.invoke(messages))
            output: ExemplarJudgeOutput = result["structured_response"]
        except Exception as error:
            raise ExemplarJudgeInvocationError("Exemplar judge failed to review the given candidates.") from error
        relevant_positions = {
            verdict.candidate_index for verdict in output.verdicts if verdict.status is ExemplarRelevance.RELEVANT
        }
        return [candidate for position, candidate in enumerate(candidates) if position in relevant_positions]


class ExemplarJury:
    """Asks every judge about the same candidates at once and keeps only those all of them call relevant."""

    def __init__(self, judges: list[ExemplarJudge]) -> None:
        self._judges = judges

    def confirm(self, code_key: CodeKey, code: str, candidates: list[Exemplar]) -> list[Exemplar]:
        """The unanimously relevant candidates, in the order given; no model call when there are none to judge.

        Raises:
            ExemplarJudgeInvocationError: If any judge fails, since a verdict missing from the
                jury cannot be told apart from a split one.
        """
        if not candidates:
            return []
        relevant_by_judge = self._ask_every_judge(code_key, code, candidates)
        for candidate in candidates:
            judges_in_favour = sum(candidate in relevant_candidates for relevant_candidates in relevant_by_judge)
            rag_metrics.record_exemplar_jury_result(judges_in_favour, len(self._judges))
        return [
            candidate
            for candidate in candidates
            if all(candidate in relevant_candidates for relevant_candidates in relevant_by_judge)
        ]

    def _ask_every_judge(self, code_key: CodeKey, code: str, candidates: list[Exemplar]) -> list[list[Exemplar]]:
        with ThreadPoolExecutor(max_workers=len(self._judges)) as executor:
            futures = [
                executor.submit(contextvars.copy_context().run, judge.pick_relevant, code_key, code, candidates)
                for judge in self._judges
            ]
        return [future.result() for future in futures]


def _build_prompt(code_key: CodeKey, code: str, candidates: list[Exemplar]) -> str:
    candidate_entries = "\n\n".join(
        f"Candidate {position}: {candidate.chunk_name} in {candidate.file_path}\n{candidate.code}"
        for position, candidate in enumerate(candidates)
    )
    principle_focus = PRINCIPLE_FOCUS.get(code_key, code_key.value)
    return f"PRINCIPLE: {principle_focus}\n\nCODE UNDER REVIEW:\n{code}\n\nCandidates:\n\n{candidate_entries}"
