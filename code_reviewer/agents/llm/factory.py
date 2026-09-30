"""
    Builds the LLMInterface configured by settings.llm_provider.
"""
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.bedrock import BedrockLLM
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.config.settings import get_settings

_PROVIDERS: dict[str, type[LLMInterface]] = {
    "ollama": OllamaLLM,
    "openrouter": OpenRouter,
    "bedrock": BedrockLLM,
}


def build_llm() -> LLMInterface:
    return _PROVIDERS[get_settings().llm_provider]()
