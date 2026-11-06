"""
    Names of the non-agent places that call a model, used as the fixed label of their LLM metrics.
"""
from enum import StrEnum


class LlmCaller(StrEnum):
    DRY_JUDGE = "DRY_JUDGE"
    CHUNK_EXPLAINER = "CHUNK_EXPLAINER"
    PAIRING_JUDGE = "PAIRING_JUDGE"
    PAIRING_REWRITER = "PAIRING_REWRITER"
    INTAKE_SCREEN = "INTAKE_SCREEN"
