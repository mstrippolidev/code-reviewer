"""
    Tests for which models make up a provider's judge panel: one per configured judge model on OpenRouter,
    and just the provider's own fast tier everywhere else.
"""
from types import SimpleNamespace

import pytest

from code_reviewer.agents.llm import openrouter
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter


def _use_settings(monkeypatch: pytest.MonkeyPatch, judge_models: str) -> None:
    fake_settings = SimpleNamespace(
        openrouter_judge_models=judge_models,
        openrouter_model="main/model",
        openrouter_fast_model="fast/model",
        fast_model_agent_keys="",
    )
    monkeypatch.setattr(openrouter, "settings", fake_settings)


def test_openrouter_panel_has_one_judge_per_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify each model named in OPENROUTER_JUDGE_MODELS becomes its own voter, in the order configured."""
    _use_settings(monkeypatch, "a/one, b/two ,c/three")

    panel = OpenRouter().for_judge_panel()

    assert [judge.model_name for judge in panel] == ["a/one", "b/two", "c/three"]


def test_openrouter_panel_without_configured_models_is_the_fast_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an unconfigured panel still gives one working judge instead of none."""
    _use_settings(monkeypatch, "")

    panel = OpenRouter().for_judge_panel()

    assert [judge.model_name for judge in panel] == ["fast/model"]


def test_a_provider_without_a_panel_votes_with_itself() -> None:
    """Verify a local run gets a panel of one, so exemplar judging still works with a single model."""
    llm = OllamaLLM()

    assert llm.for_judge_panel() == [llm]
