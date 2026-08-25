"""
    Exceptions for the RAG indexing layer: ownership checks and vector-store operation failures.
"""


class RepoOwnerRequiredError(Exception):
    """Raised when indexing content for a private repo with no owner_id — never silently indexes private content with no owner attached."""


class FileEmbeddingError(Exception):
    """Raised when splitting or embedding a file's content fails."""


class VectorStoreDeletionError(Exception):
    """Raised when removing existing chunks from the vector store fails."""


class VectorStoreWriteError(Exception):
    """Raised when writing embedded chunks to the vector store fails."""

class VectorStoreQueryError(Exception):
    """Raised when a similarity search against the vector store fails."""
