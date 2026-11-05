"""
    Names the cause of a failed file index, so a failure rate can be split without high-cardinality labels.
"""
from code_reviewer.rag.errors import (
    ChunkExplanationError,
    FileEmbeddingError,
    StructuralIndexDeletionError,
    StructuralIndexWriteError,
    VectorStoreDeletionError,
    VectorStoreWriteError,
)

_STORE_ERRORS = (
    VectorStoreDeletionError,
    VectorStoreWriteError,
    StructuralIndexDeletionError,
    StructuralIndexWriteError,
)


def classify_index_failure(error: BaseException) -> str:
    """The cause of a failed file index; a timed-out chunk explanation is told apart from other explain failures."""
    if isinstance(error, ChunkExplanationError):
        return "chunk_explain_timeout" if _has_timeout_cause(error) else "chunk_explain"
    if isinstance(error, FileEmbeddingError):
        return "embedding"
    if isinstance(error, _STORE_ERRORS):
        return "vector_store"
    return "other"


def _has_timeout_cause(error: BaseException) -> bool:
    cause = error.__cause__
    while cause is not None:
        if isinstance(cause, TimeoutError):
            return True
        cause = cause.__cause__
    return False
