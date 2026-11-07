"""
    Metric instruments for the RAG layer, recorded through the OpenTelemetry API only.
"""
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from enum import StrEnum

from opentelemetry import metrics
from opentelemetry.metrics import Histogram, Meter

from code_reviewer.telemetry.metrics import AgentOutcome, outcome_of_failure

LATENCY_BUCKETS_SECONDS = [0.05, 0.25, 1, 2, 5, 10, 30, 60, 180]
CANDIDATE_BUCKETS = [0, 1, 2, 3, 5, 10, 20, 30]
SCORE_BUCKETS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

SOURCE = "code_reviewer.source"
CORPUS = "code_reviewer.corpus"
KIND = "code_reviewer.kind"
OUTCOME = "code_reviewer.outcome"
CODE_KEY = "code_reviewer.code_key"
VERDICT = "code_reviewer.verdict"
ORIGIN = "code_reviewer.origin"
RESULT = "code_reviewer.result"


class RetrievalSource(StrEnum):
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    CODE = "code"
    LEXICAL = "lexical"
    EXEMPLAR = "exemplar"
    PAIRING_NAMES = "pairing_names"
    PAIRING_SEMANTIC = "pairing_semantic"
    PAIRING_LEXICAL = "pairing_lexical"
    PAIRING_FILE_LOOKUP = "pairing_file_lookup"
    EVIDENCE_LOOKUP = "evidence_lookup"


class Corpus(StrEnum):
    REPO = "repo"
    SHARED = "shared"


class EmbeddingKind(StrEnum):
    QUERY = "query"
    DOCUMENT = "document"


class ExemplarOutcome(StrEnum):
    INJECTED = "injected"
    JUDGED_IRRELEVANT = "judged_irrelevant"
    NO_CANDIDATES = "no_candidates"
    FAILED = "failed"


class JuryResult(StrEnum):
    UNANIMOUS_RELEVANT = "unanimous_relevant"
    UNANIMOUS_NOT_RELEVANT = "unanimous_not_relevant"
    SPLIT = "split"


class DuplicateOrigin(StrEnum):
    HISTORY = "history"
    INTRA_PR = "intra_pr"


class PairingResult(StrEnum):
    FOUND_FIRST_TRY = "found_first_try"
    FOUND_AFTER_REWRITE = "found_after_rewrite"
    NOT_FOUND = "not_found"


class EvidenceResult(StrEnum):
    FOUND = "found"
    EMPTY = "empty"
    SYMBOL_NOT_FOUND = "symbol_not_found"
    FAILED = "failed"
    NO_REPO = "no_repo"


class RagMetrics:
    """Holds the RAG layer's instruments so callers record events, not raw numbers and labels."""

    def __init__(self, meter: Meter) -> None:
        self._create_retrieval_instruments(meter)
        self._create_exemplar_instruments(meter)
        self._create_dry_instruments(meter)
        self._create_pairing_and_evidence_instruments(meter)

    def track_retrieval(self, source: RetrievalSource) -> AbstractContextManager[None]:
        """Times the enclosed search and records how it ended, re-raising any failure."""
        return self._timed(self._retrieval_duration, {SOURCE: source.value})

    def track_explain(self) -> AbstractContextManager[None]:
        """Times the enclosed chunk-explanation LLM call."""
        return self._timed(self._explain_duration, {})

    def track_embedding(self, kind: EmbeddingKind) -> AbstractContextManager[None]:
        """Times the enclosed embedding of one query or one batch of documents."""
        return self._timed(self._embedding_duration, {KIND: kind.value})

    def track_rerank(self) -> AbstractContextManager[None]:
        """Times the enclosed cross-encoder pass."""
        return self._timed(self._rerank_duration, {})

    def track_judge(self) -> AbstractContextManager[None]:
        """Times the enclosed DRY judge call."""
        return self._timed(self._judge_duration, {})

    def track_pairing(self) -> AbstractContextManager[None]:
        """Times one whole corpus-wide test-file lookup and records how it ended, re-raising any failure."""
        return self._timed(self._pairing_duration, {})

    def record_rerank_candidates(self, candidates_in: int, candidates_kept: int) -> None:
        """Reports how many candidates a re-rank pass received and how many it kept."""
        self._rerank_candidates_in.record(candidates_in)
        self._rerank_candidates_kept.record(candidates_kept)

    def record_exemplar_lookup(self, corpus: Corpus, code_key: str, outcome: ExemplarOutcome) -> None:
        """Counts one exemplar lookup by the corpus it hit, the agent that asked and how it ended."""
        self._exemplar_lookups.add(1, {CORPUS: corpus.value, CODE_KEY: code_key, OUTCOME: outcome.value})

    def record_exemplar_best_score(self, corpus: Corpus, score: float) -> None:
        """Reports the best embedding-similarity score among a lookup's candidates."""
        self._exemplar_best_score.record(score, {CORPUS: corpus.value})

    def record_exemplar_jury_result(self, judges_in_favour: int, panel_size: int) -> None:
        """Counts one candidate the exemplar jury voted on, by whether the judges agreed."""
        if judges_in_favour == panel_size:
            result = JuryResult.UNANIMOUS_RELEVANT
        elif judges_in_favour == 0:
            result = JuryResult.UNANIMOUS_NOT_RELEVANT
        else:
            result = JuryResult.SPLIT
        self._exemplar_jury_candidates.add(1, {RESULT: result.value})

    def record_dry_chunk_with_candidates(self) -> None:
        """Counts one chunk whose repo history held something worth comparing it against."""
        self._dry_chunks.add(1, {OUTCOME: "candidates"})

    def record_dry_chunk_without_candidates(self) -> None:
        """Counts one chunk with nothing similar in the repo's history."""
        self._dry_chunks.add(1, {OUTCOME: "no_candidates"})

    def record_dry_candidates(self, source: RetrievalSource, count: int) -> None:
        """Counts the candidates of one kind that survived re-ranking for a chunk."""
        self._dry_candidates.add(count, {SOURCE: source.value})

    def record_dry_exact_matches(self, origin: DuplicateOrigin, count: int) -> None:
        """Counts exact structural duplicates written up without an LLM, by where they were found."""
        self._dry_exact_matches.add(count, {ORIGIN: origin.value})

    def record_judge_call(self, candidate_count: int) -> None:
        """Reports how many candidates one judge call was asked about."""
        self._judge_candidates.record(candidate_count)

    def record_judge_verdicts(self, duplicates: int, rejected: int) -> None:
        """Counts the judge's verdicts, so the share it confirms as duplicates is visible."""
        self._judge_verdicts.add(duplicates, {VERDICT: "duplicate"})
        self._judge_verdicts.add(rejected, {VERDICT: "not_duplicate"})

    def record_pairing_result(self, result: PairingResult) -> None:
        """Counts one finished test-file lookup by whether it found a test file, and on which attempt."""
        self._pairing_lookups.add(1, {RESULT: result.value})

    def record_evidence_lookup(self, result: EvidenceResult) -> None:
        """Counts one ARCH/COUP evidence lookup by what it gave back."""
        self._evidence_lookups.add(1, {RESULT: result.value})

    @contextmanager
    def _timed(self, histogram: Histogram, labels: dict[str, str]) -> Iterator[None]:
        started = time.perf_counter()
        outcome = AgentOutcome.COMPLETED
        try:
            yield
        except BaseException as error:
            outcome = outcome_of_failure(error)
            raise
        finally:
            histogram.record(time.perf_counter() - started, {**labels, OUTCOME: outcome.value})

    def _create_retrieval_instruments(self, meter: Meter) -> None:
        """Creates the instruments that time searching, explaining, embedding and re-ranking."""
        self._retrieval_duration = _latency_histogram(
            meter, "code_reviewer.rag.retrieval.duration", "Wall time of one search, by source and how it ended"
        )
        self._explain_duration = _latency_histogram(
            meter, "code_reviewer.rag.explain.duration", "Wall time of one chunk-explanation LLM call"
        )
        self._embedding_duration = _latency_histogram(
            meter, "code_reviewer.rag.embedding.duration", "Wall time to embed one query or one batch of documents"
        )
        self._rerank_duration = _latency_histogram(
            meter, "code_reviewer.rag.rerank.duration", "Wall time of one cross-encoder pass"
        )
        self._rerank_candidates_in = meter.create_histogram(
            "code_reviewer.rag.rerank.candidates_in",
            unit="{candidate}",
            description="Candidates one re-rank pass received",
            explicit_bucket_boundaries_advisory=CANDIDATE_BUCKETS,
        )
        self._rerank_candidates_kept = meter.create_histogram(
            "code_reviewer.rag.rerank.candidates_kept",
            unit="{candidate}",
            description="Candidates one re-rank pass kept",
            explicit_bucket_boundaries_advisory=CANDIDATE_BUCKETS,
        )

    def _create_exemplar_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe how exemplar lookups ended and how the jury voted."""
        self._exemplar_lookups = meter.create_counter(
            "code_reviewer.rag.exemplar.lookups", unit="{lookup}", description="Exemplar lookups, by how they ended"
        )
        self._exemplar_best_score = meter.create_histogram(
            "code_reviewer.rag.exemplar.best_score",
            unit="{score}",
            description="Best embedding-similarity score among an exemplar lookup's candidates",
            explicit_bucket_boundaries_advisory=SCORE_BUCKETS,
        )
        self._exemplar_jury_candidates = meter.create_counter(
            "code_reviewer.rag.exemplar.jury.candidates",
            unit="{candidate}",
            description="Exemplar candidates the jury voted on, by whether the judges agreed",
        )

    def _create_dry_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe DRY's candidates, exact matches and judge."""
        self._dry_chunks = meter.create_counter(
            "code_reviewer.rag.dry.chunks", unit="{chunk}", description="Chunks checked for duplicates, by result"
        )
        self._dry_candidates = meter.create_counter(
            "code_reviewer.rag.dry.candidates",
            unit="{candidate}",
            description="Candidates that survived re-ranking, by the search that found them",
        )
        self._dry_exact_matches = meter.create_counter(
            "code_reviewer.rag.dry.exact_matches",
            unit="{match}",
            description="Exact structural duplicates written up without an LLM",
        )
        self._judge_duration = _latency_histogram(
            meter, "code_reviewer.rag.dry.judge.duration", "Wall time of one DRY judge call"
        )
        self._judge_candidates = meter.create_histogram(
            "code_reviewer.rag.dry.judge.candidates",
            unit="{candidate}",
            description="Candidates one judge call was asked about",
            explicit_bucket_boundaries_advisory=CANDIDATE_BUCKETS,
        )
        self._judge_verdicts = meter.create_counter(
            "code_reviewer.rag.dry.judge.verdicts", unit="{verdict}", description="Judge verdicts, by whether it confirmed"
        )

    def _create_pairing_and_evidence_instruments(self, meter: Meter) -> None:
        """Creates the instruments for TCASE's corpus-wide test-file lookup and the ARCH/COUP evidence tool."""
        self._pairing_duration = _latency_histogram(
            meter,
            "code_reviewer.rag.pairing.duration",
            "Wall time of one corpus-wide test-file lookup, model calls included",
        )
        self._pairing_lookups = meter.create_counter(
            "code_reviewer.rag.pairing.lookups",
            unit="{lookup}",
            description="Test-file lookups, by whether one was found and on which attempt",
        )
        self._evidence_lookups = meter.create_counter(
            "code_reviewer.rag.evidence.lookups",
            unit="{lookup}",
            description="ARCH/COUP evidence lookups, by what they gave back",
        )


def _latency_histogram(meter: Meter, name: str, description: str) -> Histogram:
    return meter.create_histogram(
        name, unit="s", description=description, explicit_bucket_boundaries_advisory=LATENCY_BUCKETS_SECONDS
    )


rag_metrics = RagMetrics(metrics.get_meter("code_reviewer"))
