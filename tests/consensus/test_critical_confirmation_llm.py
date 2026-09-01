"""
    End-to-end tests for critical confirmation against the real judge panel.
    These check that the panel discriminates a genuine critical from an
    overstated one, which no fake can tell us.
"""
import pytest
from langchain_core.messages import HumanMessage

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.consensus.critical_confirmation import CriticalConfirmation
from code_reviewer.schemas.review import (
    AgentOutput,
    AgentReviewEntry,
    CodeKey,
    Incident,
    Priority,
)

PANEL_MODELS = ["xiaomi/mimo-v2.5", "tencent/hy3", "openai/gpt-5.6-luna"]

MONEY_PATH_CODE = '''
def charge_customer(customer_id: str, amount_cents: int) -> None:
    try:
        payment_gateway.charge(customer_id, amount_cents)
        ledger.record_payment(customer_id, amount_cents)
    except Exception:
        pass
'''

CACHE_PATH_CODE = '''
def warm_thumbnail_cache(image_id: str) -> None:
    try:
        cache.set(f"thumb:{image_id}", render_thumbnail(image_id))
    except Exception:
        pass
'''


@pytest.fixture(scope="module")
def panel() -> list[LLMInterface]:
    return [OpenRouter(model_name=model) for model in PANEL_MODELS]


def _state(code: str, description: str) -> dict:
    incident = Incident(
        priority=Priority.CRITICAL,
        line_position="2-6",
        description=description,
        advice="let the exception propagate, or raise a custom exception",
    )
    return {
        "structured_response": AgentOutput(
            review=[AgentReviewEntry(code_key=CodeKey.ERR, incidents=[incident], rating=80)]
        ),
        "messages": [HumanMessage(content=code)],
    }


def _priority_after_confirmation(state: dict, panel: list[LLMInterface]) -> Priority:
    CriticalConfirmation(CodeKey.ERR, judges=panel).after_model(state, runtime=None)
    return state["structured_response"].review[0].incidents[0].priority


@pytest.mark.llm
def test_panel_upholds_a_swallowed_exception_on_a_payment_path(panel: list[LLMInterface]) -> None:
    """Verify a finding that plainly meets ERR's critical bar survives the
    panel — a bare except swallowing a failed charge and its ledger write."""
    state = _state(
        MONEY_PATH_CODE,
        "charge_customer swallows every exception, so a failed charge or an "
        "unrecorded ledger write looks identical to success to every caller",
    )

    assert _priority_after_confirmation(state, panel) == Priority.CRITICAL


@pytest.mark.llm
def test_panel_downgrades_a_swallowed_exception_on_a_cache_path(panel: list[LLMInterface]) -> None:
    """Verify a real but overstated finding is downgraded — the same swallow
    pattern on a thumbnail cache has no hard-to-reverse consequence, so it
    does not meet ERR's critical bar."""
    state = _state(
        CACHE_PATH_CODE,
        "warm_thumbnail_cache swallows every exception, hiding failures to "
        "populate the thumbnail cache",
    )

    assert _priority_after_confirmation(state, panel) == Priority.HIGH
