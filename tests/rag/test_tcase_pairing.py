"""
    Tests for PairingCandidateFinder's bucket logic against a fake indexed
    corpus — no vector store, embedding, or LLM call.
"""
from code_reviewer.rag.code_similarity_index import LexicalMatch
from code_reviewer.rag.indexer import FileChunk, SimilarChunk
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.tcase_pairing import (
    DETERMINISTIC_CANDIDATE_CAP,
    SEMANTIC_FUSION_CAP,
    PairingCandidateFinder,
    PairingEvidenceSources,
)
from code_reviewer.schemas.submission import SubmittedFile

REPO = RepoData(repo_id="1", commit_sha="abc123", owner_id="7")
SOURCE = SubmittedFile(file_path="shop/payment.py", content="def charge(amount):\n    return amount\n")


_DEFAULT_CHUNKS = [
    FileChunk(file_path="", chunk_name="test_b", start_line=10, end_line=11, text="", code="def test_b(): ..."),
    FileChunk(file_path="", chunk_name="test_a", start_line=1, end_line=2, text="", code="def test_a(): ..."),
]


class FakeEmbeddingIndex:
    """Stands in for LlamaIndexRagManager over a fixed set of indexed files."""

    def __init__(
        self,
        indexed_paths: list[str],
        dense_hits: list[str] | None = None,
        chunks_by_path: dict[str, list[FileChunk]] | None = None,
    ) -> None:
        self._indexed_paths = indexed_paths
        self._dense_hits = dense_hits or []
        self._chunks_by_path = chunks_by_path or {}
        self.find_similar_codes: list[str] = []
        self.find_similar_queries: list[str] = []

    def list_indexed_file_paths(self, repo_id: str, owner_id: str | None) -> list[str]:
        return self._indexed_paths

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[SimilarChunk]:
        self.find_similar_codes.append(code)
        return [_similar_chunk(path) for path in self._dense_hits]

    def find_similar_by_query(self, repo_data: RepoData, query: str, top_k: int = 5) -> list[SimilarChunk]:
        self.find_similar_queries.append(query)
        return [_similar_chunk(path) for path in self._dense_hits]

    def get_file_chunks(self, repo_id: str, owner_id: str | None, file_path: str) -> list[FileChunk]:
        return self._chunks_by_path.get(file_path, _DEFAULT_CHUNKS)


class FakeCodeSimilarityIndex:
    def __init__(self, lexical_hits: list[str] | None = None) -> None:
        self._lexical_hits = lexical_hits or []
        self.lexical_queries: list[str] = []

    def find_lexical_matches(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[LexicalMatch]:
        self.lexical_queries.append(code)
        return [
            LexicalMatch(file_path=path, chunk_name="test_x", start_line=1, end_line=2, code="", score=1.0)
            for path in self._lexical_hits
        ]


def _similar_chunk(file_path: str) -> SimilarChunk:
    return SimilarChunk(file_path=file_path, chunk_name="test_x", start_line=1, end_line=2, text="", score=0.9, code="")


def _finder(embedding_index: FakeEmbeddingIndex, code_index: FakeCodeSimilarityIndex | None = None) -> PairingCandidateFinder:
    return PairingCandidateFinder(PairingEvidenceSources(embedding_index, code_index or FakeCodeSimilarityIndex()))


def test_deterministic_bucket_keeps_only_test_files_sharing_the_source_stem() -> None:
    """Verify naming-convention candidates must be test files whose stem matches the source's."""
    index = FakeEmbeddingIndex(["shop/payment.py", "tests/test_payment.py", "tests/test_orders.py", "shop/payment_helpers.py"])

    buckets = _finder(index).find_candidates(REPO, SOURCE)

    assert [candidate.file_path for candidate in buckets.deterministic] == ["tests/test_payment.py"]


def test_deterministic_bucket_is_capped() -> None:
    """Verify a common stem shared by many test files never floods the judge."""
    paths = [f"pkg{index}/test_payment.py" for index in range(DETERMINISTIC_CANDIDATE_CAP + 2)]
    index = FakeEmbeddingIndex(paths)

    buckets = _finder(index).find_candidates(REPO, SOURCE)

    assert len(buckets.deterministic) == DETERMINISTIC_CANDIDATE_CAP


def test_semantic_bucket_ranks_a_file_both_methods_found_above_either_alone() -> None:
    """Verify reciprocal rank fusion rewards consensus between dense and lexical search.

    test_checkout is only 2nd in the dense list and 1st in the lexical
    list, but agreement between both methods should still outrank
    test_billing, which only the dense search found at all.
    """
    index = FakeEmbeddingIndex([], dense_hits=["tests/test_billing.py", "tests/test_checkout.py"])
    code_index = FakeCodeSimilarityIndex(lexical_hits=["tests/test_checkout.py", "tests/test_refunds.py"])

    buckets = _finder(index, code_index).find_candidates(REPO, SOURCE)

    assert [candidate.file_path for candidate in buckets.semantic] == [
        "tests/test_checkout.py", "tests/test_billing.py", "tests/test_refunds.py"
    ]


def test_semantic_bucket_fusion_deduplicates_a_file_found_by_both_methods() -> None:
    """Verify a file both search methods surfaced appears exactly once, not twice."""
    index = FakeEmbeddingIndex([], dense_hits=["tests/test_checkout.py"])
    code_index = FakeCodeSimilarityIndex(lexical_hits=["tests/test_checkout.py"])

    buckets = _finder(index, code_index).find_candidates(REPO, SOURCE)

    assert len(buckets.semantic) == 1


def test_semantic_bucket_is_capped_after_fusion() -> None:
    """Verify the fused semantic bucket never floods the reranker beyond its cap."""
    dense_hits = [f"tests/test_{index}.py" for index in range(SEMANTIC_FUSION_CAP + 3)]
    index = FakeEmbeddingIndex([], dense_hits=dense_hits)

    buckets = _finder(index).find_candidates(REPO, SOURCE)

    assert len(buckets.semantic) == SEMANTIC_FUSION_CAP


def test_semantic_bucket_drops_non_test_files() -> None:
    """Verify a semantically similar source file is never offered as a test file."""
    index = FakeEmbeddingIndex([], dense_hits=["shop/billing.py", "tests/test_billing.py"])

    buckets = _finder(index).find_candidates(REPO, SOURCE)

    assert [candidate.file_path for candidate in buckets.semantic] == ["tests/test_billing.py"]


def test_semantic_bucket_excludes_files_already_in_the_deterministic_bucket() -> None:
    """Verify a file found by both buckets is only offered once, in the deterministic bucket."""
    index = FakeEmbeddingIndex(["tests/test_payment.py"], dense_hits=["tests/test_payment.py"])

    buckets = _finder(index).find_candidates(REPO, SOURCE)

    assert buckets.semantic == []


def test_first_attempt_explains_the_source_code() -> None:
    """Verify the dense search runs on the source's code when no rewritten query is given."""
    index = FakeEmbeddingIndex([])

    _finder(index).find_candidates(REPO, SOURCE)

    assert index.find_similar_codes == [SOURCE.content]


def test_rewritten_query_is_embedded_directly() -> None:
    """Verify a retry's natural-language query skips the code-explain step."""
    index = FakeEmbeddingIndex([])

    _finder(index).find_candidates(REPO, SOURCE, semantic_query="tests calling charge with a declined card")

    assert index.find_similar_queries == ["tests calling charge with a declined card"]


def test_rewritten_query_also_drives_the_lexical_search() -> None:
    """Verify BM25 searches the rewritten query's vocabulary on retry, not the source code again."""
    code_index = FakeCodeSimilarityIndex()

    _finder(FakeEmbeddingIndex([]), code_index).find_candidates(REPO, SOURCE, semantic_query="charge declined card")

    assert code_index.lexical_queries == ["charge declined card"]


def test_candidate_content_joins_indexed_chunks_in_source_order() -> None:
    """Verify a candidate's content reads top to bottom, whatever order the store returned chunks in.

    Neither default chunk mentions SOURCE's only symbol, charge, so both
    are kept via the narrowing's own no-match fallback.
    """
    index = FakeEmbeddingIndex(["tests/test_payment.py"])

    buckets = _finder(index).find_candidates(REPO, SOURCE)

    assert buckets.deterministic[0].content == "def test_a(): ...\ndef test_b(): ..."


def test_candidate_content_keeps_only_chunks_mentioning_a_source_symbol() -> None:
    """Verify a chunk that never mentions any of the source's own symbols is left out."""
    chunks = {
        "tests/test_payment.py": [
            FileChunk(file_path="tests/test_payment.py", chunk_name="test_charge", start_line=1, end_line=2, text="", code="def test_charge():\n    assert charge(5) == 5"),
            FileChunk(file_path="tests/test_payment.py", chunk_name="test_unrelated", start_line=4, end_line=5, text="", code="def test_unrelated():\n    assert format_currency(5) == '$5'"),
        ]
    }
    index = FakeEmbeddingIndex(["tests/test_payment.py"], chunks_by_path=chunks)

    buckets = _finder(index).find_candidates(REPO, SOURCE)

    assert buckets.deterministic[0].content == "def test_charge():\n    assert charge(5) == 5"


def test_candidate_content_falls_back_to_every_chunk_when_none_mention_a_symbol() -> None:
    """Verify a candidate with no literal reference to the source's symbols isn't dropped to nothing."""
    chunks = {
        "tests/test_payment.py": [
            FileChunk(file_path="tests/test_payment.py", chunk_name="test_indirect", start_line=1, end_line=2, text="", code="def test_indirect():\n    assert getattr(module, 'charge_it')(5) == 5"),
        ]
    }
    index = FakeEmbeddingIndex(["tests/test_payment.py"], chunks_by_path=chunks)

    buckets = _finder(index).find_candidates(REPO, SOURCE)

    assert buckets.deterministic[0].content == "def test_indirect():\n    assert getattr(module, 'charge_it')(5) == 5"


def test_candidate_content_uses_the_whole_candidate_when_the_source_has_no_symbols() -> None:
    """Verify an unparseable or empty source degrades to sending every chunk, not zero."""
    unparseable_source = SubmittedFile(file_path="shop/broken.py", content="def broken(:\n")
    chunks = {
        "tests/test_broken.py": [
            FileChunk(file_path="tests/test_broken.py", chunk_name="test_a", start_line=1, end_line=2, text="", code="def test_a(): ..."),
        ]
    }
    index = FakeEmbeddingIndex(["tests/test_broken.py"], chunks_by_path=chunks)

    buckets = _finder(index).find_candidates(REPO, unparseable_source)

    assert buckets.deterministic[0].content == "def test_a(): ..."
