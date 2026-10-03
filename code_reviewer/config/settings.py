from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from code_reviewer.schemas.review import CodeKey, SizeStatus

SIZE_STATUS_LINE_THRESHOLDS: dict[SizeStatus, int] = {
    SizeStatus.SOFT_LIMIT: 500,
    SizeStatus.HARD_LIMIT_EXCEEDED: 750,
}

AGENT_WEIGHTS: dict[CodeKey, float] = {
    CodeKey.SOLID1: 2.0,
    CodeKey.SOLID2: 2.0,
    CodeKey.COH: 2.0,
    CodeKey.COUP: 2.0,
    CodeKey.TEST: 2.0,
    CodeKey.TCASE: 1.5,
    CodeKey.CONC: 1.5,
    CodeKey.CMPLX: 1.5,
    CodeKey.ARCH: 1.5,
    CodeKey.BOUND: 1.5,
    CodeKey.VAR: 1.0,
    CodeKey.DRY: 1.0,
    CodeKey.ERR: 1.0,
    CodeKey.CMT: 0.5,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str
    ollama_llm_model: str
    ollama_embed_model: str
    ollama_code_embed_model: str
    ollama_embed_num_ctx: int = 8192
    ollama_llm_num_ctx: int = 8192

    openrouter_api_key: str
    openrouter_model: str
    openrouter_fast_model: str = "google/gemini-3.8-flash"
    openrouter_judge_models: str = ""
    fast_model_agent_keys: str = ""

    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str

    environment: str

    max_submission_characters: int
    max_files_per_submission: int

    max_file_lines: int

    guardrails_api_key: str

    max_batch_concurrency: int = 4
    max_dispatch_concurrency: int = 4
    max_intake_screen_concurrency: int = 4

    exemplar_relevance_floor: float = 0.5
    exemplar_top_k: int = 2

    dry_rerank_max_candidates: int = 3

    dry_judge_max_pair_chars: int = 4000
    dry_judge_split_overlap_chars: int = 400

    llm_call_timeout_seconds: float = 60.0
    dry_agent_timeout_seconds: float = 300.0

    llm_provider: Literal["ollama", "openrouter", "bedrock"] = "ollama"
    embedding_provider: Literal["ollama", "bedrock"] = "ollama"

    bedrock_region: str = "us-east-2"
    bedrock_llm_model: str = "deepseek.v3-v1:0"



@lru_cache
def get_settings() -> Settings:
    return Settings()
