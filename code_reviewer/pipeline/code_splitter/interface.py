"""
    Interface file for code split logic.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class CodeChunk:
    """Represents one extracted AST block: a top-level function or class."""
    chunk_type: str
    name: str
    code: str
    start_line: int
    end_line: int


class CodeSplitterInterface(ABC):
    """Contract for splitting one language's source into per-function/class chunks."""

    @abstractmethod
    def split_code(self, content: str) -> list[CodeChunk]:
        """Split source code into one chunk per top-level function or class.

        Args:
            content: The file's full source code, already decoded to text —
                implementations never receive raw bytes; decoding happens
                once, at the network/ingestion edge, before this is called.

        Returns:
            One CodeChunk per top-level function or class definition, in
            source order.

        Raises:
            CodeChunkingError: If content cannot be parsed as valid syntax
                for this language.
        """
