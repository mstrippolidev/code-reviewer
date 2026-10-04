"""
    Checks recursion_limit_for_tool_calls against LangGraph's real step counting, with a fake model: no LLM calls.
"""
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import after_model
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel

from code_reviewer.agents import base
from code_reviewer.agents.base import recursion_limit_for_tool_calls

MAX_LOOKUPS = 3


class FinalAnswer(BaseModel):
    done: bool


@tool
def lookup_file(file_path: str) -> str:
    """Return a file's content."""
    return "content"


class ToolCallingFakeModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolCallingFakeModel":
        return self


def _noop_after_model_hooks() -> list:
    """One stand-in per real after_model hook, since each costs a graph step whatever it does."""
    hooks = []
    for index in range(len(base._AFTER_MODEL_HOOKS)):
        @after_model(name=f"noop_hook_{index}")
        def noop(state: Any, runtime: Any) -> dict[str, Any]:
            return {}
        hooks.append(noop)
    return hooks


def _run_agent_making_lookups(lookup_count: int) -> None:
    turns = [
        AIMessage(content="", tool_calls=[{"name": "lookup_file", "args": {"file_path": f"f{i}.py"}, "id": f"call{i}"}])
        for i in range(lookup_count)
    ]
    turns.append(AIMessage(content="", tool_calls=[{"name": "FinalAnswer", "args": {"done": True}, "id": "final"}]))
    agent = create_agent(
        model=ToolCallingFakeModel(messages=iter(turns)),
        tools=[lookup_file],
        middleware=_noop_after_model_hooks(),
        response_format=ToolStrategy(FinalAnswer),
    )
    agent.invoke(
        {"messages": [("user", "review this file")]},
        config={"recursion_limit": recursion_limit_for_tool_calls(MAX_LOOKUPS)},
    )


def test_the_allowed_number_of_lookups_fits_the_budget() -> None:
    """Verify an agent can use every lookup it is allowed and still answer, with the real hook count."""
    _run_agent_making_lookups(MAX_LOOKUPS)


def test_lookups_well_beyond_the_allowance_are_cut_off() -> None:
    """Verify the budget is still a bound, so a looping model fails instead of spending without end."""
    with pytest.raises(GraphRecursionError):
        _run_agent_making_lookups(MAX_LOOKUPS + 2)
