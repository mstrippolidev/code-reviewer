"""
    Merges every agent's per-file results into one weighted PR-level report.
"""
from collections import defaultdict

from code_reviewer.config.settings import AGENT_WEIGHTS
from code_reviewer.schemas.review import (
    AgentReviewEntry,
    AggregatedReviewEntry,
    AggregatorOutput,
    Incident,
    Meta,
    PrRecommendation,
    Priority,
    SkippedFile,
)
from code_reviewer.schemas.submission import PreparedFile

_APPROVED_RATING_THRESHOLD = 85
_REJECTED_RATING_THRESHOLD = 60
_HARD_LIMIT_SKIP_REASON = "file_exceeds_hard_limit"


class Aggregator:
    """Builds the final AggregatorOutput from one submission's raw agent
    results. Stateless, like Vote — every method call is independent."""

    def build_output(
        self,
        entries: list[AgentReviewEntry],
        prepared_files: list[PreparedFile],
        skipped_files: list[SkippedFile],
    ) -> AggregatorOutput:
        """Merges every agent's per-file result into the final weighted report.

        Args:
            entries: One AgentReviewEntry per agent per reviewed file.
            prepared_files: Every file that reached agent dispatch, in review order.
            skipped_files: Every file skipped before dispatch, with its reason.

        Returns:
            One merged entry per reviewed file, plus PR-level meta.
        """
        entries_by_file = self._group_entries_by_file(entries)
        review = [
            self._build_file_entry(prepared_file, entries_by_file[prepared_file.source_file.file_path])
            for prepared_file in prepared_files
        ]
        return AggregatorOutput(meta=self._build_meta(entries, review, skipped_files), review=review)

    def _group_entries_by_file(self, entries: list[AgentReviewEntry]) -> dict[str, list[AgentReviewEntry]]:
        grouped: dict[str, list[AgentReviewEntry]] = defaultdict(list)
        for entry in entries:
            grouped[entry.file_path].append(entry)
        return grouped

    def _build_file_entry(self, prepared_file: PreparedFile, entries: list[AgentReviewEntry]) -> AggregatedReviewEntry:
        rated_entries = self._exclude_unrated(entries)
        agents_skipped = [entry.code_key for entry in rated_entries if entry.rating == 0]
        return AggregatedReviewEntry(
            file_path=prepared_file.source_file.file_path,
            rating=round(self._weighted_rating(rated_entries)),
            code_key=sorted({entry.code_key for entry in rated_entries if entry.incidents}),
            file_lines=f"1-{prepared_file.source_file.content.count(chr(10))}",
            size_status=prepared_file.size_status,
            review_scope=prepared_file.review_scope,
            agents_skipped=agents_skipped,
            agents_failed=[entry.code_key for entry in entries if entry.failed],
            skip_reason=_HARD_LIMIT_SKIP_REASON if agents_skipped else None,
            incidents=self._merge_incidents(rated_entries),
        )

    def _exclude_unrated(self, entries: list[AgentReviewEntry]) -> list[AgentReviewEntry]:
        """Drops a failed or skipped agent's weight from rating/incidents
        entirely, rather than counting it as a rating-0 result — that would
        wrongly read as the deterministic hard-limit case to every caller below."""
        return [entry for entry in entries if not entry.failed and not entry.skipped]

    def _merge_incidents(self, entries: list[AgentReviewEntry]) -> list[Incident]:
        return [
            incident.model_copy(update={"code_key": entry.code_key})
            for entry in entries
            for incident in entry.incidents
        ]

    def _weighted_rating(self, entries: list[AgentReviewEntry]) -> float:
        if not entries:
            return 100.0
        weighted_sum = sum(entry.rating * AGENT_WEIGHTS[entry.code_key] for entry in entries)
        total_weight = sum(AGENT_WEIGHTS[entry.code_key] for entry in entries)
        return weighted_sum / total_weight

    def _build_meta(
        self,
        entries: list[AgentReviewEntry],
        review: list[AggregatedReviewEntry],
        skipped_files: list[SkippedFile],
    ) -> Meta:
        overall_rating = self._weighted_rating(self._exclude_unrated(entries))
        recommendation, rejection_reason = self._recommend(overall_rating, review)
        incident_counts = self._count_incidents_by_priority(review)
        return Meta(
            total_files_in_pr=len(review) + len(skipped_files),
            total_files_reviewed=len(review),
            overall_rating=overall_rating,
            critical_incidents=incident_counts[Priority.CRITICAL],
            high_incidents=incident_counts[Priority.HIGH],
            medium_incidents=incident_counts[Priority.MEDIUM],
            low_incidents=incident_counts[Priority.LOW],
            agents_run=sorted({entry.code_key for entry in entries}),
            pr_recommendation=recommendation,
            rejection_reason=rejection_reason,
            skipped_files=skipped_files,
        )

    def _count_incidents_by_priority(self, review: list[AggregatedReviewEntry]) -> dict[Priority, int]:
        counts = {priority: 0 for priority in Priority}
        for file_entry in review:
            for incident in file_entry.incidents:
                counts[incident.priority] += 1
        return counts

    def _recommend(
        self, overall_rating: float, review: list[AggregatedReviewEntry]
    ) -> tuple[PrRecommendation, str | None]:
        hard_limit_file = self._first_hard_limit_file(review)
        if hard_limit_file is not None:
            return PrRecommendation.REJECTED, f"{hard_limit_file} exceeded the file size hard limit."
        critical = self._first_critical_incident(review)
        if critical is not None:
            file_path, description = critical
            return PrRecommendation.REJECTED, f"Critical incident in {file_path}: {description}"
        if overall_rating < _REJECTED_RATING_THRESHOLD:
            return PrRecommendation.REJECTED, f"Weighted rating {overall_rating:.1f} is below {_REJECTED_RATING_THRESHOLD}."
        if overall_rating > _APPROVED_RATING_THRESHOLD:
            return PrRecommendation.APPROVED, None
        return PrRecommendation.NEEDS_WORK, None

    def _first_hard_limit_file(self, review: list[AggregatedReviewEntry]) -> str | None:
        for file_entry in review:
            if file_entry.agents_skipped:
                return file_entry.file_path
        return None

    def _first_critical_incident(self, review: list[AggregatedReviewEntry]) -> tuple[str, str] | None:
        for file_entry in review:
            for incident in file_entry.incidents:
                if incident.priority == Priority.CRITICAL:
                    return file_entry.file_path, incident.description
        return None
