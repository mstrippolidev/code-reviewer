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


class StructuralHashError(Exception):
    """Raised when a code chunk cannot be parsed to compute its structural hash."""


class StructuralIndexChunkingError(Exception):
    """Raised when a file cannot be split into chunks for structural hashing."""


class StructuralIndexWriteError(Exception):
    """Raised when writing structural hashes to the index fails."""


class StructuralIndexDeletionError(Exception):
    """Raised when removing existing structural hashes from the index fails."""


class StructuralIndexQueryError(Exception):
    """Raised when an exact-hash lookup against the structural index fails."""


class DryMatchingChunkingError(Exception):
    """Raised when a file cannot be split into chunks for duplicate matching."""


class ChunkExplanationError(Exception):
    """Raised when generating a code chunk's short explanation fails."""


class UnsupportedExemplarPrincipleError(Exception):
    """Raised when promoting a candidate for a principle whose exemplars no agent retrieves."""
