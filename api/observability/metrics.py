"""
    Metric instruments for the review lifecycle, recorded through the OpenTelemetry API only.
"""
import time
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum

from opentelemetry import metrics
from opentelemetry.metrics import Meter

from api.db.models.indexed_file import IndexedFileStatus
from api.db.models.registered_repo import RepoIndexStatus
from api.db.models.similar_code_search import SimilarCodeSearchStatus
from api.observability.index_failure import classify_index_failure
from api.observability.review_outcome import ReviewKind, ReviewOutcome

QUEUE_WAIT_BUCKETS_SECONDS = [1, 5, 15, 30, 60, 120, 300, 600, 1800]
REVIEW_DURATION_BUCKETS_SECONDS = [30, 60, 120, 300, 600, 900, 1800, 3600]
SEARCH_DURATION_BUCKETS_SECONDS = [1, 5, 10, 30, 60, 120, 300, 600]
FILE_INDEX_DURATION_BUCKETS_SECONDS = [0.5, 1, 2, 5, 10, 20, 30, 60, 120, 180, 300]
FILE_COUNT_BUCKETS = [1, 2, 3, 5, 8, 10, 15]
UNFINISHED_BUCKETS = [0, 1, 2, 3, 4, 5, 8, 10]
_COUNTED_FILE_STATUSES = (IndexedFileStatus.INDEXED, IndexedFileStatus.SKIPPED, IndexedFileStatus.FAILED)

REVIEW_KIND = "code_reviewer.review_kind"
RESULT = "code_reviewer.result"
SIZE_STATUS = "code_reviewer.size_status"
FILE_STATUS = "code_reviewer.file_status"
CAUSE = "code_reviewer.cause"
GUARD = "code_reviewer.guard"
SCOPE = "code_reviewer.scope"
TIER = "code_reviewer.tier"
MODEL = "code_reviewer.model"


class ReviewResult(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"


class AliveResult(StrEnum):
    OK = "ok"
    FAILED = "failed"


class CapGuard(StrEnum):
    UNFINISHED_REVIEWS = "unfinished_reviews"
    UNFINISHED_INDEXINGS = "unfinished_indexings"
    REVIEW_SLOT_BUSY = "review_slot_busy"


class ApiMetrics:
    """Holds the API's instruments so callers record events, not raw numbers and labels."""

    def __init__(self, meter: Meter) -> None:
        self._queue_wait = meter.create_histogram(
            "code_reviewer.review.queue_wait",
            unit="s",
            description="Time from a review job's creation until a worker started it",
            explicit_bucket_boundaries_advisory=QUEUE_WAIT_BUCKETS_SECONDS,
        )
        self._duration = meter.create_histogram(
            "code_reviewer.review.duration",
            unit="s",
            description="Wall time of one review's pipeline run, from worker start to report",
            explicit_bucket_boundaries_advisory=REVIEW_DURATION_BUCKETS_SECONDS,
        )
        self._finished = meter.create_counter(
            "code_reviewer.review.finished", unit="{review}", description="Reviews that ended, by result"
        )
        self._files = meter.create_histogram(
            "code_reviewer.review.files",
            unit="{file}",
            description="Files reviewed per finished review",
            explicit_bucket_boundaries_advisory=FILE_COUNT_BUCKETS,
        )
        self._files_failed = meter.create_counter(
            "code_reviewer.review.files_failed", unit="{file}", description="Files lost to an unexpected failure"
        )
        self._file_size_status = meter.create_counter(
            "code_reviewer.review.file_size_status", unit="{file}", description="Reviewed files by size status"
        )
        self._create_search_instruments(meter)
        self._create_indexing_instruments(meter)
        self._create_guard_instruments(meter)
        self._alive_check_runs = meter.create_counter(
            "code_reviewer.alive_check.runs", unit="{call}", description="Daily probe calls to a model tier, by result"
        )

    def record_review_started(self, kind: ReviewKind, queue_wait_seconds: float) -> None:
        """Reports how long a review job waited before a worker picked it up."""
        self._queue_wait.record(queue_wait_seconds, {REVIEW_KIND: kind.value})

    def record_review_finished(self, kind: ReviewKind, result: ReviewResult, seconds: float) -> None:
        """Reports how a review's pipeline run ended and how long it took."""
        labels = {REVIEW_KIND: kind.value, RESULT: result.value}
        self._duration.record(seconds, labels)
        self._finished.add(1, labels)

    def record_review_outcome(self, kind: ReviewKind, outcome: ReviewOutcome) -> None:
        """Reports the shape of a finished review's report: its files, lost files and size mix."""
        labels = {REVIEW_KIND: kind.value}
        self._files.record(outcome.file_count, labels)
        self._files_failed.add(outcome.failed_file_count, labels)
        for size_status, count in outcome.size_status_counts.items():
            self._file_size_status.add(count, {**labels, SIZE_STATUS: size_status})

    def record_search_started(self, queue_wait_seconds: float) -> None:
        """Reports how long a similar-code search waited before a worker picked it up."""
        self._search_queue_wait.record(queue_wait_seconds)

    def record_search_checked(self, status: SimilarCodeSearchStatus, seconds: float) -> None:
        """Reports how long a search's duplicate check took and how it ended."""
        self._search_duration.record(seconds, {RESULT: status.value})

    def record_search_finished(self, status: SimilarCodeSearchStatus) -> None:
        """Counts one search that reached a final status, however it got there."""
        self._search_finished.add(1, {RESULT: status.value})

    @contextmanager
    def track_file_indexing(self) -> Iterator[None]:
        """Times the enclosed embedding of one file and records the cause if it fails, re-raising any failure."""
        started = time.perf_counter()
        result = IndexedFileStatus.INDEXED
        try:
            yield
        except BaseException as error:
            result = IndexedFileStatus.FAILED
            self._index_file_failures.add(1, {CAUSE: classify_index_failure(error)})
            raise
        finally:
            self._index_file_duration.record(time.perf_counter() - started, {RESULT: result.value})

    def record_repo_finished(self, status: RepoIndexStatus, file_counts: dict[IndexedFileStatus, int]) -> None:
        """Counts one repo that finished indexing and the files it ended with, by status."""
        self._index_repo_finished.add(1, {RESULT: status.value})
        for file_status in _COUNTED_FILE_STATUSES:
            self._index_files.add(file_counts.get(file_status, 0), {FILE_STATUS: file_status.value})

    def record_rate_limit_refusal(self, scope: str) -> None:
        """Counts one request refused by a per-minute rate limit, by the route group that limit protects."""
        self._guard_refusals.add(1, {GUARD: "rate_limit", SCOPE: scope})

    def record_cap_refusal(self, guard: CapGuard) -> None:
        """Counts one request refused by a cap on a user's unfinished work, or by the slot lock timing out."""
        self._guard_refusals.add(1, {GUARD: guard.value})

    def record_unfinished_reviews(self, unfinished: int) -> None:
        """Reports how many unfinished reviews a user had when the cap was checked."""
        self._unfinished_reviews.record(unfinished)

    def record_unfinished_indexings(self, unfinished: int) -> None:
        """Reports how many unfinished indexings a user had when the cap was checked."""
        self._unfinished_indexings.record(unfinished)

    def record_alive_check(self, tier: str, model: str, result: AliveResult) -> None:
        """Counts one probe call made to a model tier and whether it came back as a parsed review."""
        self._alive_check_runs.add(1, {TIER: tier, MODEL: model, RESULT: result.value})

    def _create_guard_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe the cost guards."""
        self._guard_refusals = meter.create_counter(
            "code_reviewer.guard.refusals", unit="{request}", description="Requests refused by a cost guard"
        )
        self._unfinished_reviews = meter.create_histogram(
            "code_reviewer.guard.unfinished_reviews",
            unit="{review}",
            description="Unfinished reviews a user had when the cap was checked",
            explicit_bucket_boundaries_advisory=UNFINISHED_BUCKETS,
        )
        self._unfinished_indexings = meter.create_histogram(
            "code_reviewer.guard.unfinished_indexings",
            unit="{repo}",
            description="Unfinished indexings a user had when the cap was checked",
            explicit_bucket_boundaries_advisory=UNFINISHED_BUCKETS,
        )

    def _create_search_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe similar-code searches."""
        self._search_queue_wait = meter.create_histogram(
            "code_reviewer.search.queue_wait",
            unit="s",
            description="Time from a search's creation until a worker started it",
            explicit_bucket_boundaries_advisory=QUEUE_WAIT_BUCKETS_SECONDS,
        )
        self._search_duration = meter.create_histogram(
            "code_reviewer.search.duration",
            unit="s",
            description="Wall time of one search's duplicate check, by how it ended",
            explicit_bucket_boundaries_advisory=SEARCH_DURATION_BUCKETS_SECONDS,
        )
        self._search_finished = meter.create_counter(
            "code_reviewer.search.finished", unit="{search}", description="Searches that reached a final status"
        )

    def _create_indexing_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe repo and file indexing."""
        self._index_file_duration = meter.create_histogram(
            "code_reviewer.index.file.duration",
            unit="s",
            description="Wall time to embed one file, queueing for a slot excluded",
            explicit_bucket_boundaries_advisory=FILE_INDEX_DURATION_BUCKETS_SECONDS,
        )
        self._index_file_failures = meter.create_counter(
            "code_reviewer.index.file.failures", unit="{file}", description="Files that failed to embed, by cause"
        )
        self._index_files = meter.create_counter(
            "code_reviewer.index.files", unit="{file}", description="Files a finished repo ended with, by status"
        )
        self._index_repo_finished = meter.create_counter(
            "code_reviewer.index.repo.finished", unit="{repo}", description="Repos that finished indexing, by result"
        )


api_metrics = ApiMetrics(metrics.get_meter("api"))
