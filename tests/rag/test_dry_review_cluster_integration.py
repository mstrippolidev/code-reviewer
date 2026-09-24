"""
    Real-model validation of DRY's clustering fix, against the exact shape
    observed manually on service/common/error_handlers.py: 6 near-identical
    handlers came back as 18 incidents at rating 0. Judged for real against
    OpenRouter (this project's configured OPENROUTER_MODEL, the same
    provider DRY runs on in production), the merged cluster must come back
    as at most one incident per handler.
"""
import pytest

from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.rag.dry_judge import DryJudge
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.dry_review import build_dry_review_entry
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.structural_hash_store import StructuralMatch
from code_reviewer.schemas.review import AgentReviewEntry

FILE_PATH = "service/common/error_handlers.py"

_HANDLERS = [
    ("bad_request", 400),
    ("not_found", 404),
    ("method_not_supported", 405),
    ("conflict", 409),
    ("mediatype_not_supported", 415),
    ("internal_server_error", 500),
]


def _handler_code(name: str, status: int) -> str:
    message = name.replace("_", " ")
    return (
        f"def {name}(request, exc):\n"
        f'    logger.error("{message}: %s", exc)\n'
        f'    return JSONResponse(status_code={status}, content={{"error": str(exc)}})\n'
    )


def _build_file_and_chunks() -> tuple[str, list[StructuralMatch]]:
    lines: list[str] = []
    chunks: list[StructuralMatch] = []
    for name, status in _HANDLERS:
        start_line = len(lines) + 1
        lines.extend(_handler_code(name, status).splitlines())
        end_line = len(lines)
        chunks.append(StructuralMatch(file_path=FILE_PATH, chunk_name=name, start_line=start_line, end_line=end_line))
        lines.append("")
    return "\n".join(lines) + "\n", chunks


FILE_CONTENT, _CHUNKS = _build_file_and_chunks()


def _as_candidate(chunk: StructuralMatch) -> SimilarChunk:
    body = "\n".join(FILE_CONTENT.splitlines()[chunk.start_line - 1 : chunk.end_line])
    return SimilarChunk(
        file_path=chunk.file_path, chunk_name=chunk.chunk_name, start_line=chunk.start_line, end_line=chunk.end_line,
        text=chunk.chunk_name, score=0.9, code=body,
    )


def _history_matches() -> list[ChunkHistoryMatch]:
    """Each handler's own search finds only the next handler in the list,
    never the whole group — a real top-k retrieval over near-duplicates
    would miss some siblings too. Clustering's transitive closure over
    this ring is what has to pull all 6 into one cluster."""
    matches = []
    for index, chunk in enumerate(_CHUNKS):
        neighbor = _CHUNKS[(index + 1) % len(_CHUNKS)]
        matches.append(ChunkHistoryMatch(chunk=chunk, structural_matches=[], semantic_matches=[_as_candidate(neighbor)]))
    return matches


@pytest.fixture(scope="module")
def review_entry() -> AgentReviewEntry:
    dry_judge = DryJudge(llm=OpenRouter())
    return build_dry_review_entry(FILE_PATH, FILE_CONTENT, [], _history_matches(), dry_judge)


@pytest.mark.llm
def test_near_duplicate_handler_cluster_is_confirmed(review_entry: AgentReviewEntry) -> None:
    assert review_entry.incidents != []


@pytest.mark.llm
def test_near_duplicate_handler_cluster_reports_at_most_one_incident_per_handler(
    review_entry: AgentReviewEntry,
) -> None:
    assert len(review_entry.incidents) <= len(_HANDLERS)
