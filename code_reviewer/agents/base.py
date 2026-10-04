"""
    Base agent class all 14 review agents inherit from.
"""

import logging
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.structured_output import ResponseFormat, ToolStrategy
from langchain_core.tools import BaseTool

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.middleware import (
    dedupe_tool_calls,
    discard_model_reported_failure,
    retry_missing_structured_output,
    retry_model,
    retry_transient_call,
    calculate_rating,
    rating_from_incidents,
)
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.config.settings import get_settings
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import (
    AgentOutput,
    AgentReviewEntry,
    CodeKey,
    Incident,
    Priority,
    SizeStatus,
)

logger = logging.getLogger(__name__)

_AFTER_MODEL_HOOKS = (calculate_rating, discard_model_reported_failure)
_STRUCTURED_OUTPUT_CORRECTION_TURNS = 1


def recursion_limit_for_tool_calls(max_tool_calls: int) -> int:
    """Graph step budget for up to max_tool_calls tool round-trips, one structured-output correction and the answer.

    LangGraph runs every after_model hook as its own step after each model turn, so a hand-picked limit
    silently loses tool budget whenever a hook is added; deriving it from the hook count keeps it honest.
    """
    steps_per_model_turn = 1 + len(_AFTER_MODEL_HOOKS)
    tool_steps = max_tool_calls + _STRUCTURED_OUTPUT_CORRECTION_TURNS
    model_turns = tool_steps + 1
    return model_turns * steps_per_model_turn + tool_steps


class AgentInvocationError(Exception):
    """Raised when an agent's LLM call fails or its output cannot be validated."""


@dataclass(frozen=True)
class ReviewContext:
    """Immutable per-invocation repo scoping, injected into a bound tool's
    ToolRuntime.context — never something the model can see or set itself."""

    repo_id: str | None = None
    owner_id: str | None = None


@dataclass(frozen=True)
class FileReviewMeta:
    """Size and repo-scoping metadata for one file-agent review call,
    bundled so FileSizeAwareAgentBase.execute_agent stays within this
    project's 3-parameter limit as agents need more than raw code and
    file_path to work with."""

    size_status: SizeStatus = SizeStatus.NORMAL
    repo_data: RepoData | None = None


class AgentBase:
    """Owns the LangChain wiring (model init, prompt templating, structured-output
    calls) shared by all 14 review agents."""

    def __init__(
        self,
        code_agent: CodeKey,
        system_prompt: str,
        llm: LLMInterface | None = None,
    ) -> None:
        """Wire up the LangChain agent for one review agent.

        Args:
            code_agent: This agent's CodeKey, stamped onto every review entry.
            system_prompt: This agent's review instructions.
            llm: Provider to run against. Defaults to a local OllamaLLM()
                when not given.
        """
        self._code_agent = code_agent
        self._system_prompt = system_prompt
        llm_factory = llm if llm is not None else OllamaLLM()
        tools = self._build_tools()
        self._agent = create_agent(
            model=llm_factory.create_raw_model(),
            tools=tools,
            system_prompt=self._system_prompt,
            middleware=[
                *self._retry_middleware(tools),
                *self._tool_loop_guard(tools),
                *self._extra_middleware(),
                *_AFTER_MODEL_HOOKS,
            ],
            response_format=self._response_format(llm_factory, tools),
            context_schema=self._context_schema(),
        )

    def _response_format(
        self, llm_factory: LLMInterface, tools: list[BaseTool] | None
    ) -> ResponseFormat[AgentOutput]:
        """A provider's native structured output constrains decoding to the
        schema, which leaves the model unable to emit a tool call at all —
        so an agent with tools has to take structured output as a tool
        call instead, and only a toolless one can use the provider's own."""
        if tools:
            return ToolStrategy(AgentOutput)
        return llm_factory.build_response_format(AgentOutput)

    def _retry_middleware(self, tools: list[BaseTool] | None) -> list[AgentMiddleware]:
        """retry_model exists to give ProviderStrategy the retry-on-
        validation-failure behavior ToolStrategy already has natively via
        handle_errors — stacking both on a tool-carrying agent would just
        retry the same failure twice. retry_transient_call applies either
        way, since neither strategy retries a rate limit or a timeout."""
        if tools:
            return [retry_transient_call, retry_missing_structured_output]
        return [retry_transient_call, retry_model]

    def _tool_loop_guard(self, tools: list[BaseTool] | None) -> list[AgentMiddleware]:
        """A model with no reasoning trace can lose track of already having
        a tool's result and keep re-asking instead of finalizing — this
        only applies to agents that have tools at all."""
        return [dedupe_tool_calls] if tools else []

    def get_agent_key(self) -> CodeKey:
        """Returns this agent's own CodeKey."""
        return self._code_agent

    def get_system_prompt(self) -> str:
        """Returns this agent's review instructions."""
        return self._system_prompt

    def _build_tools(self) -> list[BaseTool] | None:
        """Tools this agent's model can call mid-review. Empty for every
        agent except the ones needing a cross-file evidence hop (ARCH,
        COUP) — override in a subclass that sets its own dependencies
        before calling super().__init__()."""
        return None

    def _extra_middleware(self) -> list[AgentMiddleware]:
        """Middleware this agent needs beyond the shared retry and rating
        steps. Empty for every agent except the ones given an exemplar
        corpus to draw few-shot context from."""
        return []

    def _recursion_limit(self) -> int:
        """Graph step budget for one invocation. Higher for agents whose
        _build_tools() returns something, since a tool round-trip costs
        extra model/tool steps beyond a single structured-output call."""
        return 4

    def _context_schema(self) -> type | None:
        """Shape of this agent's immutable per-invocation context, injected
        into a bound tool's ToolRuntime.context. None for every agent
        except the ones needing a cross-file evidence hop (ARCH, COUP)."""
        return None

    def execute_agent_batch(self, chunks: list[str], file_path: str | None = None) -> list[AgentOutput]:
        """Review each given chunk and return this agent's structured
        findings for every one, executed concurrently via LangChain's batch().

        Args:
            chunks: The source code chunks to review, one call per item.
            file_path: Path of the file being reviewed, relative to the
                repo root. Stamped onto every result, same as execute_agent.

        Returns:
            One AgentOutput per chunk, in the same order as chunks.

        Raises:
            AgentInvocationError: If any call fails or its output cannot
                be validated against AgentOutput.
        """
        results = self._invoke_batch(chunks)
        for result in results:
            self._set_file_path_and_code_key(result, file_path)
        return results

    def _invoke_batch(self, chunks: list[str]) -> list[AgentOutput]:
        """Run this agent's prompt against each chunk, one call per chunk,
        executed concurrently instead of sequentially.

        Args:
            chunks: The source code chunks this agent is reviewing.

        Returns:
            One AgentOutput per chunk, in the same order as chunks.

        Raises:
            AgentInvocationError: If any call fails or its output cannot
                be validated against AgentOutput.
        """
        payloads = [{"messages": [{"role": "user", "content": code}]} for code in chunks]
        config = {"max_concurrency": get_settings().max_batch_concurrency}
        try:
            results = call_with_hard_timeout(lambda: self._agent.batch(payloads, config=config))
            return [result["structured_response"] for result in results]
        except Exception as error:
            logger.error("Agent %s failed to review the given code.", self._code_agent, exc_info=True)
            raise AgentInvocationError(
                f"Agent {self._code_agent} failed to review the given code."
            ) from error

    def execute_agent(
        self, code: str, file_path: str | None = None, repo_data: RepoData | None = None
    ) -> AgentOutput:
        """Review the given code and return this agent's structured findings.

        Args:
            code: The source code (or chunk) to review.
            file_path: Path of the file being reviewed, relative to the repo
                root. Only meaningful for PR or whole-file reviews — leave
                as None when reviewing a standalone snippet with no file.
            repo_data: Repo scoping for this file's submission, used only by
                agents whose _build_tools()/_context_schema() need it (ARCH,
                COUP). None for a standalone review with no repo context.

        Returns:
            This agent's structured review of the given code.

        Raises:
            AgentInvocationError: If the LLM call fails or its output
                cannot be validated against AgentOutput.
        """
        result = self._invoke(code, repo_data)
        self._set_file_path_and_code_key(result, file_path)
        return result

    def _invoke(self, code: str, repo_data: RepoData | None = None) -> AgentOutput:
        """Run this agent's prompt against the given source code and return its review.

        Args:
            code: The source code (or chunk) this agent is reviewing.

        Returns:
            This agent's structured review of the given code.

        Raises:
            AgentInvocationError: If the LLM call fails or its output
                cannot be validated against AgentOutput.
        """
        messages = {
            "messages": [
                {
                    "role": "user",
                    "content": code
                }
            ]
        }
        config = {"recursion_limit": self._recursion_limit()}
        invoke_kwargs: dict[str, object] = {"config": config}
        if repo_data is not None:
            invoke_kwargs["context"] = ReviewContext(repo_id=repo_data.repo_id, owner_id=repo_data.owner_id)
        try:
            result = call_with_hard_timeout(lambda: self._agent.invoke(messages, **invoke_kwargs))
            return result["structured_response"]
        except Exception as error:
            logger.error("Agent %s failed to review the given code.", self._code_agent, exc_info=True)
            raise AgentInvocationError(
                f"Agent {self._code_agent} failed to review the given code."
            ) from error

    def _set_file_path_and_code_key(self, result: AgentOutput, file_path: str | None) -> None:
        """Stamps result with the caller-known file_path and this agent's own CodeKey."""
        self._merge_extra_review_entries(result)
        self._set_file_path(result, file_path)
        self._set_code_key(result)

    def _merge_extra_review_entries(self, result: AgentOutput) -> None:
        """One execute_agent/-batch call reviews exactly one file or chunk,
        so review must carry exactly one entry — but a tool-carrying agent
        sometimes adds a second entry for a file it only fetched as
        evidence. Which entry is "the real one" isn't knowable from the
        output alone, and every downstream caller reads review[0], so
        merge rather than pick: a real finding must never be silently
        dropped by an arbitrary index."""
        if len(result.review) <= 1:
            return
        logger.warning(
            "Agent %s returned %d review entries for one call; merging into one.",
            self._code_agent,
            len(result.review),
        )
        incidents = [incident for entry in result.review for incident in entry.incidents]
        result.review = [
            AgentReviewEntry(code_key=self._code_agent, incidents=incidents, rating=rating_from_incidents(incidents))
        ]

    def _set_file_path(self, result: AgentOutput, file_path: str | None) -> None:
        """Stamp every review entry with the caller-known file_path.

        The model is never asked to report file_path — it has no reliable
        way to know it — so the caller's value always wins, including
        overwriting with None.
        """
        for entry in result.review:
            entry.file_path = file_path

    def _set_code_key(self, result: AgentOutput) -> None:
        """Stamp every review entry with this agent's own CodeKey.

        The model is asked to report code_key too, but testing showed it
        cannot reliably self-identify.
        """
        for entry in result.review:
            entry.code_key = self._code_agent


class FileSizeAwareAgentBase(AgentBase):
    """AgentBase for agents that need full-file context (SOLID2, COH, COUP,
    ARCH, BOUND). Short-circuits to a fixed rating-0 result without an LLM
    call when size_status is HARD_LIMIT_EXCEEDED; otherwise behaves exactly
    like AgentBase."""

    def execute_agent(
        self,
        code: str,
        file_path: str | None = None,
        review_meta: FileReviewMeta | None = None,
    ) -> AgentOutput:
        """Review the given code, short-circuiting to a fixed rating-0
        result instead of an LLM call when the file exceeds the hard limit.

        Args:
            code: The full file content to review.
            file_path: Path of the file being reviewed, relative to the
                repo root.
            review_meta: This file's size classification and (for the
                ARCH/COUP evidence hop) repo scoping. Only
                HARD_LIMIT_EXCEEDED changes behavior here.

        Returns:
            This agent's structured review of the given code, or the fixed
            hard-limit result when size_status is HARD_LIMIT_EXCEEDED.
        """
        review_meta = review_meta or FileReviewMeta()
        if review_meta.size_status == SizeStatus.HARD_LIMIT_EXCEEDED:
            return self._hard_limit_result(code, file_path)
        return super().execute_agent(code, file_path, review_meta.repo_data)

    def _hard_limit_result(self, code: str, file_path: str | None) -> AgentOutput:
        """Builds the fixed rating-0 result for a file too large for
        full-file context, without spending an LLM call on it."""
        line_count = code.count("\n")
        incident = Incident(
            priority=Priority.HIGH,
            line_position=f"1-{line_count}",
            description=(
                f"File has {line_count} lines exceeding the hard size limit. "
                f"{self._code_agent} analysis requires full file context, which "
                "cannot be guaranteed at this size."
            ),
            advice="Split this file into smaller modules under 500 lines each, grouped by responsibility.",
        )
        agent_review_entry = AgentReviewEntry(
            file_path=file_path,
            rating=0,
            code_key=self._code_agent,
            incidents=[incident],
        )
        return AgentOutput(review=[agent_review_entry])
