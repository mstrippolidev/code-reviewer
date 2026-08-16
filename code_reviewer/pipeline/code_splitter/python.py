"""
    Concrete class to split Python code into per-function/class chunks.
"""
import ast

from code_reviewer.pipeline.code_splitter.errors import CodeChunkingError
from code_reviewer.pipeline.code_splitter.interface import CodeChunk, CodeSplitterInterface

_ChunkNode = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


class PythonCodeSplit(CodeSplitterInterface):
    """Splits Python source into one chunk per top-level function or class."""

    def split_code(self, content: str) -> list[CodeChunk]:
        """Split Python source into one chunk per top-level function or class.

        Args:
            content: The file's full Python source, already decoded to text.

        Returns:
            One CodeChunk per top-level function or class definition, in
            source order. Nested functions/classes stay embedded inside
            their parent's chunk rather than becoming chunks of their own.

        Raises:
            CodeChunkingError: If content is not valid Python syntax, or a
                chunk's source cannot be extracted from it.
        """
        tree = self._parse(content)
        source_lines = content.splitlines()
        return [
            self._build_chunk(node, source_lines)
            for node in tree.body
            if isinstance(node, _ChunkNode)
        ]

    def _parse(self, content: str) -> ast.Module:
        try:
            return ast.parse(content)
        except (SyntaxError, ValueError) as error:
            raise CodeChunkingError("Failed to parse source as valid Python syntax.") from error

    def _build_chunk(self, node: _ChunkNode, source_lines: list[str]) -> CodeChunk:
        start_line = self._chunk_start_line(node)
        end_line = node.end_lineno if node.end_lineno is not None else node.lineno
        code = "\n".join(source_lines[start_line - 1 : end_line])
        if not code:
            raise CodeChunkingError(f"Could not extract source for '{node.name}' at line {start_line}.")
        return CodeChunk(
            chunk_type=type(node).__name__,
            name=node.name,
            code=code,
            start_line=start_line,
            end_line=end_line,
        )

    def _chunk_start_line(self, node: _ChunkNode) -> int:
        """Returns the line this chunk should start at, including any
        decorators — node.lineno alone points at the def/class keyword,
        excluding decorator lines above it."""
        if node.decorator_list:
            return min(decorator.lineno for decorator in node.decorator_list)
        return node.lineno
