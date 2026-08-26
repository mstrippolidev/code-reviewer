"""
    Exact-match store for structural clone hashes: one row per indexed
    function/class chunk, queryable by exact structural_hash equality.
"""
from dataclasses import dataclass

from sqlalchemy import Column, Delete, Engine, Integer, MetaData, Select, String, Table, create_engine, delete, insert, select

from code_reviewer.pipeline.code_splitter.errors import CodeChunkingError
from code_reviewer.pipeline.code_splitter.interface import CodeChunk
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.rag.errors import (
    RepoOwnerRequiredError,
    StructuralIndexChunkingError,
    StructuralIndexDeletionError,
    StructuralIndexQueryError,
    StructuralIndexWriteError,
)
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash import compute_structural_hash
from code_reviewer.rag.vector_store import build_connection_url


@dataclass
class StructuralMatch:
    """One indexed chunk whose structural_hash exactly matches a query."""

    file_path: str
    chunk_name: str
    start_line: int
    end_line: int


def _build_default_engine() -> Engine:
    return create_engine(build_connection_url("postgresql+psycopg2"))


def _build_table(metadata: MetaData) -> Table:
    return Table(
        "structural_hashes",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("repo_id", String, nullable=False, index=True),
        Column("owner_id", String, nullable=True),
        Column("file_path", String, nullable=False),
        Column("chunk_name", String, nullable=False),
        Column("chunk_type", String, nullable=False),
        Column("start_line", Integer, nullable=False),
        Column("end_line", Integer, nullable=False),
        Column("structural_hash", String, nullable=False, index=True),
    )


class StructuralHashStore:
    """Keeps one repo's per-function structural hashes in sync with its
    current file content, for exact-match Type-1/2/3 clone lookups.
    """

    def __init__(self, engine: Engine | None = None, schema_name: str | None = "code_reviewer") -> None:
        self._engine = engine or _build_default_engine()
        self._metadata = MetaData(schema=schema_name)
        self._table = _build_table(self._metadata)
        self._metadata.create_all(self._engine, checkfirst=True)

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None:
        """Replace one file's stored structural hashes with freshly computed
        ones from its current content.

        Raises:
            RepoOwnerRequiredError: If repo_data has no owner_id.
            StructuralIndexChunkingError: If content cannot be split or hashed.
            StructuralIndexWriteError: If writing the new rows fails.
        """
        if repo_data.owner_id is None:
            raise RepoOwnerRequiredError(
                f"Repo {repo_data.repo_id!r} has no owner_id — required before indexing its content."
            )
        rows = self._build_rows(repo_data, file_path, content)
        self.delete_file(repo_data.repo_id, file_path)
        self._insert_rows(rows)

    def _build_rows(self, repo_data: RepoData, file_path: str, content: str) -> list[dict[str, object]]:
        try:
            chunks = PythonCodeSplit().split_code(content)
        except CodeChunkingError as error:
            raise StructuralIndexChunkingError(f"Could not chunk {file_path!r} for structural hashing.") from error
        return [self._chunk_to_row(repo_data, file_path, chunk) for chunk in chunks]

    def _chunk_to_row(self, repo_data: RepoData, file_path: str, chunk: CodeChunk) -> dict[str, object]:
        return {
            "repo_id": repo_data.repo_id,
            "owner_id": repo_data.owner_id,
            "file_path": file_path,
            "chunk_name": chunk.name,
            "chunk_type": chunk.chunk_type,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "structural_hash": compute_structural_hash(chunk.code),
        }

    def _insert_rows(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        try:
            with self._engine.begin() as connection:
                connection.execute(insert(self._table), rows)
        except Exception as error:
            raise StructuralIndexWriteError("Failed to write structural hashes to the index.") from error

    def delete_file(self, repo_id: str, file_path: str) -> None:
        """Remove every stored hash for one file. A no-op if none exist yet.

        Raises:
            StructuralIndexDeletionError: If the delete itself fails.
        """
        statement = delete(self._table).where(
            self._table.c.repo_id == repo_id, self._table.c.file_path == file_path
        )
        self._execute_delete(statement, f"file {file_path!r} in repo {repo_id!r}")

    def delete_repo(self, repo_id: str) -> None:
        """Remove every stored hash for a repo. A no-op if none exist yet.

        Raises:
            StructuralIndexDeletionError: If the delete itself fails.
        """
        statement = delete(self._table).where(self._table.c.repo_id == repo_id)
        self._execute_delete(statement, f"repo {repo_id!r}")

    def _execute_delete(self, statement: Delete, description: str) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(statement)
        except Exception as error:
            raise StructuralIndexDeletionError(f"Failed to delete structural hashes for {description}.") from error

    def find_by_hash(self, repo_id: str, owner_id: str | None, structural_hash: str) -> list[StructuralMatch]:
        """Find every indexed chunk whose structural hash exactly matches,
        scoped to repo_id AND owner_id.

        Raises:
            StructuralIndexQueryError: If the query fails.
        """
        statement = select(self._table).where(
            self._table.c.repo_id == repo_id,
            self._table.c.owner_id == owner_id,
            self._table.c.structural_hash == structural_hash,
        )
        return [self._row_to_match(row) for row in self._execute_query(statement)]

    def _row_to_match(self, row: object) -> StructuralMatch:
        return StructuralMatch(
            file_path=row.file_path, chunk_name=row.chunk_name, start_line=row.start_line, end_line=row.end_line
        )

    def _execute_query(self, statement: Select) -> list:
        try:
            with self._engine.connect() as connection:
                return connection.execute(statement).fetchall()
        except Exception as error:
            raise StructuralIndexQueryError("Structural hash lookup failed.") from error
