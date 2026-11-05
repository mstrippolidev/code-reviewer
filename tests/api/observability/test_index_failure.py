"""
    Tests for classify_index_failure: the low-cardinality cause named for a file that failed to index.
"""
import pytest

from api.observability.index_failure import classify_index_failure
from code_reviewer.rag.errors import (
    ChunkExplanationError,
    FileEmbeddingError,
    StructuralIndexWriteError,
    VectorStoreDeletionError,
    VectorStoreWriteError,
)


def _explanation_failure_caused_by(cause: BaseException) -> ChunkExplanationError:
    error = ChunkExplanationError("explain failed")
    error.__cause__ = cause
    return error


def test_a_chunk_explanation_that_timed_out_is_told_apart() -> None:
    """Verify a timeout on the explain call is its own cause, since it is the failure the OpenRouter contention note describes."""
    error = _explanation_failure_caused_by(TimeoutError("hard timeout"))

    assert classify_index_failure(error) == "chunk_explain_timeout"


def test_a_timeout_deeper_in_the_cause_chain_is_still_found() -> None:
    """Verify the timeout is found even when another exception wraps it."""
    wrapped = RuntimeError("wrapper")
    wrapped.__cause__ = TimeoutError("hard timeout")

    assert classify_index_failure(_explanation_failure_caused_by(wrapped)) == "chunk_explain_timeout"


def test_a_chunk_explanation_without_a_timeout_is_a_plain_explain_failure() -> None:
    """Verify an explain failure for any other reason is not reported as a timeout."""
    error = _explanation_failure_caused_by(ValueError("bad output"))

    assert classify_index_failure(error) == "chunk_explain"


def test_a_chunk_explanation_with_no_cause_is_a_plain_explain_failure() -> None:
    """Verify a bare explain failure does not raise while looking for a cause."""
    assert classify_index_failure(ChunkExplanationError("explain failed")) == "chunk_explain"


def test_an_embedding_failure_is_named_embedding() -> None:
    """Verify a file that could not be split or embedded is the embedding cause."""
    assert classify_index_failure(FileEmbeddingError("embed failed")) == "embedding"


@pytest.mark.parametrize(
    "error",
    [VectorStoreDeletionError("x"), VectorStoreWriteError("x"), StructuralIndexWriteError("x")],
    ids=lambda error: type(error).__name__,
)
def test_a_store_failure_is_named_vector_store(error: Exception) -> None:
    """Verify failures writing to or clearing either index share one cause."""
    assert classify_index_failure(error) == "vector_store"


def test_an_unknown_error_is_named_other() -> None:
    """Verify an error this module does not know still gets a bounded label."""
    assert classify_index_failure(RuntimeError("boom")) == "other"
