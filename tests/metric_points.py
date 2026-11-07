"""
    Reads back what an in-memory metric reader collected, so tests can assert on single instruments.
"""
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader, NumberDataPoint

AGENT_RUN_DURATION = "code_reviewer.agent.run.duration"
AGENT_MODEL_TURNS = "code_reviewer.agent.model_turns"
AGENT_TOOL_CALLS = "code_reviewer.agent.tool_calls"
AGENT_SKIPPED = "code_reviewer.agent.skipped"
AGENT_RESULTS = "code_reviewer.agent.results"
AGENT_INCIDENTS = "code_reviewer.agent.incidents"
AGENT_RATING = "code_reviewer.agent.rating"
AGENT_INVALID_LINE_POSITIONS = "code_reviewer.agent.invalid_line_positions"
AGENT_INCIDENT_OVERLAPS = "code_reviewer.agent.incident_overlaps"
FILE_SKIPPED = "code_reviewer.file.skipped"
INTAKE_REJECTIONS = "code_reviewer.intake.rejections"
REVIEW_RATING = "code_reviewer.review.rating"
REVIEW_COST = "code_reviewer.review.cost"
REVIEW_QUEUE_WAIT = "code_reviewer.review.queue_wait"
REVIEW_DURATION = "code_reviewer.review.duration"
REVIEW_FINISHED = "code_reviewer.review.finished"
REVIEW_FILES = "code_reviewer.review.files"
REVIEW_FILES_FAILED = "code_reviewer.review.files_failed"
REVIEW_FILE_SIZE_STATUS = "code_reviewer.review.file_size_status"
SEARCH_QUEUE_WAIT = "code_reviewer.search.queue_wait"
SEARCH_DURATION = "code_reviewer.search.duration"
SEARCH_FINISHED = "code_reviewer.search.finished"
INDEX_FILE_DURATION = "code_reviewer.index.file.duration"
INDEX_FILE_FAILURES = "code_reviewer.index.file.failures"
INDEX_FILES = "code_reviewer.index.files"
INDEX_REPO_FINISHED = "code_reviewer.index.repo.finished"
GUARD_REFUSALS = "code_reviewer.guard.refusals"
GUARD_UNFINISHED_REVIEWS = "code_reviewer.guard.unfinished_reviews"
GUARD_UNFINISHED_INDEXINGS = "code_reviewer.guard.unfinished_indexings"
KAFKA_PRODUCER_MESSAGES = "code_reviewer.kafka.producer.messages"
KAFKA_DLQ_MESSAGES = "code_reviewer.kafka.dlq.messages"
KAFKA_CONSUMER_MESSAGES = "code_reviewer.kafka.consumer.messages"
KAFKA_HANDLER_DURATION = "code_reviewer.kafka.consumer.handler_duration"
KAFKA_CONSUMER_CRASHES = "code_reviewer.kafka.consumer.crashes"
KAFKA_CONSUMER_LAG = "code_reviewer.kafka.consumer.lag"
RAG_RETRIEVAL_DURATION = "code_reviewer.rag.retrieval.duration"
RAG_EXPLAIN_DURATION = "code_reviewer.rag.explain.duration"
RAG_EMBEDDING_DURATION = "code_reviewer.rag.embedding.duration"
RAG_RERANK_DURATION = "code_reviewer.rag.rerank.duration"
RAG_RERANK_CANDIDATES_IN = "code_reviewer.rag.rerank.candidates_in"
RAG_RERANK_CANDIDATES_KEPT = "code_reviewer.rag.rerank.candidates_kept"
RAG_PAIRING_DURATION = "code_reviewer.rag.pairing.duration"
RAG_PAIRING_LOOKUPS = "code_reviewer.rag.pairing.lookups"
RAG_EVIDENCE_LOOKUPS = "code_reviewer.rag.evidence.lookups"
RAG_EXEMPLAR_LOOKUPS = "code_reviewer.rag.exemplar.lookups"
RAG_EXEMPLAR_BEST_SCORE = "code_reviewer.rag.exemplar.best_score"
RAG_EXEMPLAR_JURY_CANDIDATES = "code_reviewer.rag.exemplar.jury.candidates"
RAG_DRY_CHUNKS = "code_reviewer.rag.dry.chunks"
RAG_DRY_CANDIDATES = "code_reviewer.rag.dry.candidates"
RAG_DRY_EXACT_MATCHES = "code_reviewer.rag.dry.exact_matches"
RAG_JUDGE_DURATION = "code_reviewer.rag.dry.judge.duration"
RAG_JUDGE_CANDIDATES = "code_reviewer.rag.dry.judge.candidates"
RAG_JUDGE_VERDICTS = "code_reviewer.rag.dry.judge.verdicts"
LLM_TOKENS ="code_reviewer.llm.tokens"
LLM_CALL_DURATION = "code_reviewer.llm.call.duration"
LLM_CALL_ERRORS = "code_reviewer.llm.call.errors"
LLM_CALLS_IN_FLIGHT = "code_reviewer.llm.calls.in_flight"
LLM_COST = "code_reviewer.llm.cost"
LLM_UNPRICED_CALLS = "code_reviewer.llm.unpriced_calls"

MetricPoint = HistogramDataPoint | NumberDataPoint


def points_for(reader: InMemoryMetricReader, metric_name: str) -> list[MetricPoint]:
    """Every data point collected for one instrument, empty when nothing was recorded on it."""
    data = reader.get_metrics_data()
    if data is None:
        return []
    return [
        point
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == metric_name
        for point in metric.data.data_points
    ]


def point_with(reader: InMemoryMetricReader, metric_name: str, attributes: dict[str, str]) -> MetricPoint:
    """The data point of one instrument whose attributes include all the given ones.

    Raises:
        LookupError: If no point matches, which means the instrument never recorded that combination.
    """
    for point in points_for(reader, metric_name):
        if attributes.items() <= dict(point.attributes).items():
            return point
    raise LookupError(f"{metric_name} has no data point with attributes {attributes}")
