"""
    Base agent class all 14 review agents inherit from.
"""

import logging

from langchain_core.prompts import ChatPromptTemplate

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.schemas.review import CodeKey, AgentOutput

logger = logging.getLogger(__name__)


class AgentInvocationError(Exception):
    """Raised when an agent's LLM call fails or its output cannot be validated."""


class AgentBase:
    """Owns the LangChain wiring (model init, prompt templating, structured-output
    calls) shared by all 14 review agents."""

    def __init__(
        self,
        code_agent: CodeKey,
        system_prompt: str,
        llm: LLMInterface | None = None,
    ) -> None:
        self._code_agent = code_agent
        self._system_prompt = system_prompt
        llm_factory = llm if llm is not None else OllamaLLM()
        self._llm = llm_factory.create_model(AgentOutput)

    def get_agent_key(self) -> CodeKey:
        return self._code_agent

    def get_system_prompt(self) -> str:
        return self._system_prompt

    def execute_agent(self, code: str, file_path: str | None = None) -> AgentOutput:
        """Review the given code and return this agent's structured findings.

        Args:
            code: The source code (or chunk) to review.
            file_path: Path of the file being reviewed, relative to the repo
                root. Only meaningful for PR or whole-file reviews — leave
                as None when reviewing a standalone snippet with no file.
        """
        result = self._invoke(code)
        self._set_file_path(result, file_path)
        self._set_code_key(result)
        return result

    def _invoke(self, code: str) -> AgentOutput:
        """Run this agent's prompt against the given source code and return its review.

        Args:
            code: The source code (or chunk) this agent is reviewing.

        Raises:
            AgentInvocationError: If the LLM call fails or its output
                cannot be validated against AgentOutput.
        """
        chat_template = ChatPromptTemplate([
            ("system", self._system_prompt),
            ("human", "{code}"),
        ])
        chain = chat_template | self._llm
        try:
            return chain.invoke({"code": code})
        except Exception as error:
            logger.error("Agent %s failed to review the given code.", self._code_agent)
            raise AgentInvocationError(
                f"Agent {self._code_agent} failed to review the given code."
            ) from error

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