"""
    Rebuilds the Python source of one indexed file from its stored chunks, so
    the call-depth walk can read files that were not part of the PR.

    The index keeps one chunk per top-level function or class, and each chunk
    carries the file's import statements in its metadata. The rebuilt source is
    those import lines followed by every chunk's code in file order.

    Example: for a file indexed as
        from app.rules import apply_rule

        class PricingManager:
            def price_for(self, price): return apply_rule(price)

    load("app/pricing.py") returns the same two parts back as one source text.
    Line numbers in the rebuilt source do not match the original file; the
    walk only needs its structure.
"""
from code_reviewer.rag.indexer import FileChunk, LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData


class ChunkFileLoader:
    def __init__(self, rag_manager: LlamaIndexRagManager, repo_data: RepoData) -> None:
        self._rag_manager = rag_manager
        self._repo_data = repo_data

    def load(self, path: str) -> str:
        chunks = self._rag_manager.get_file_chunks(self._repo_data.repo_id, self._repo_data.owner_id, path)
        code_chunks = sorted((chunk for chunk in chunks if chunk.code), key=lambda chunk: chunk.start_line)
        if not code_chunks:
            raise FileNotFoundError(f"no indexed code for {path!r}")
        return "\n\n".join([*self._import_lines(code_chunks), *(chunk.code for chunk in code_chunks)])

    def _import_lines(self, chunks: list[FileChunk]) -> list[str]:
        return list(dict.fromkeys(statement for chunk in chunks for statement in chunk.imports))
