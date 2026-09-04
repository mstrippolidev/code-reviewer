"""
    Shared fixtures for the two agents that carry a cross-file evidence
    tool (ARCH, COUP): a real Postgres-backed rag_manager, and a reporter
    that prints the model's own reasoning and tool calls.
"""
from typing import Iterator

import pytest
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.postgres import PGVectorStore

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.rag.chunk_explainer import ChunkExplainer
from code_reviewer.rag.custom_transformation import ExplainedChunkSplitter
from code_reviewer.rag.embedding.ollama_code import OllamaCodeEmbeddingProvider
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.vector_store import create_vector_store_instance

INTEGRATION_TEST_SCHEMA = "code_reviewer_test"
INTEGRATION_TEST_REPO_ID = "cross-file-evidence-integration-test-repo"


@pytest.fixture
def integration_repo_data() -> RepoData:
    return RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")


@pytest.fixture
def integration_vector_store() -> Iterator[PGVectorStore]:
    """Real PGVectorStore pointed at an isolated test schema, never the
    production code_reviewer schema."""
    vector_store = create_vector_store_instance(schema_name=INTEGRATION_TEST_SCHEMA)

    yield vector_store

    vector_store.delete_nodes(
        filters=MetadataFilters(filters=[MetadataFilter(key="repo_id", value=INTEGRATION_TEST_REPO_ID)])
    )
    vector_store.client.dispose()


@pytest.fixture
def integration_rag_manager(integration_vector_store: PGVectorStore, small_llm: LLMInterface) -> LlamaIndexRagManager:
    """Real LlamaIndexRagManager: real ExplainedChunkSplitter, real Ollama
    code embedding, real Postgres — backed by small_llm so --llm-provider
    selects the explainer's backend too."""
    embedding = OllamaCodeEmbeddingProvider()
    explainer = ChunkExplainer(llm=small_llm)
    pipeline = IngestionPipeline(transformations=[ExplainedChunkSplitter(explainer), embedding.create_embedding_model()])
    return LlamaIndexRagManager(
        vector_store=integration_vector_store, embedding=embedding, explainer=explainer, pipeline=pipeline
    )


def report_agent_reasoning(raw_result: dict) -> None:
    """Prints the model's own reasoning and tool calls (pytest -s to see
    it). A silent tool call is exactly how three separate bugs stayed
    hidden here: the model kept reasoning that it needed to check another
    file while being structurally unable to emit the call."""
    for index, message in enumerate(raw_result.get("messages", [])):
        print(f"\n--- [{index}] {type(message).__name__} ---")
        reasoning = getattr(message, "additional_kwargs", {}).get("reasoning_content")
        if reasoning:
            print("REASONING:", reasoning)
        if getattr(message, "content", ""):
            print("CONTENT:", str(message.content)[:1500])
        for call in getattr(message, "tool_calls", []) or []:
            print("TOOL_CALL:", call.get("name"), call.get("args"))


def evidence_tool_calls(raw_result: dict) -> list[dict]:
    """Every get_file_chunks call the model made during one review."""
    return [
        call
        for message in raw_result["messages"]
        for call in (getattr(message, "tool_calls", []) or [])
        if call.get("name") == "get_file_chunks"
    ]
