"""
    Tests that DRY's per-file workflow reports itself to the metrics hook: timed when it runs, counted when
    it is skipped. The workflow itself is replaced by a stub, since this checks only the reporting around it.
"""
from typing import cast

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.pipeline import dry_check
from code_reviewer.pipeline.dry_check import run_dry
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile
from code_reviewer.telemetry.metrics import PipelineMetrics
from tests.metric_points import AGENT_RUN_DURATION, AGENT_SKIPPED, point_with, points_for

_NO_CONTAINER = cast(AgentsContainer, None)


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics
) -> None:
    """Points the DRY workflow at the private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(dry_check, "pipeline_metrics", isolated_pipeline_metrics)


def _prepared_file(repo_data: RepoData | None) -> PreparedFile:
    return PreparedFile(
        source_file=SubmittedFile(file_path="service.py", content="def f():\n    return 1\n"),
        size_status=SizeStatus.NORMAL,
        repo_data=repo_data,
    )


def _with_repo() -> PreparedFile:
    return _prepared_file(RepoData(repo_id="1", commit_sha="abc", owner_id="owner-1"))


def test_run_dry_without_a_repo_counts_a_skip_with_the_repo_required_reason(metric_reader: InMemoryMetricReader) -> None:
    """Verify a guest review, which has no repo history to compare against, is counted as a DRY skip."""
    run_dry(_NO_CONTAINER, _prepared_file(None))

    assert point_with(metric_reader, AGENT_SKIPPED, {"code_reviewer.code_key": "DRY", "code_reviewer.reason": "repo_required"}).value == 1


def test_run_dry_without_a_repo_is_not_timed_as_a_run(metric_reader: InMemoryMetricReader) -> None:
    """Verify a skipped DRY adds nothing to the duration histogram, or guest reviews would drag it toward zero."""
    run_dry(_NO_CONTAINER, _prepared_file(None))

    assert points_for(metric_reader, AGENT_RUN_DURATION) == []


def test_run_dry_with_a_repo_times_the_workflow_as_a_completed_run(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a finished DRY review is recorded as a completed run under the DRY code_key."""
    clean_entry = AgentReviewEntry(file_path="service.py", code_key=CodeKey.DRY, incidents=[])
    monkeypatch.setattr(dry_check, "_review_against_history", lambda *arguments: clean_entry)

    run_dry(_NO_CONTAINER, _with_repo())

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.code_key": "DRY", "code_reviewer.outcome": "completed"}).count == 1


def test_run_dry_records_a_failed_run_when_the_workflow_raises(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a DRY workflow that raises is recorded as failed and the error still reaches the caller."""

    def explode(*arguments: object) -> AgentReviewEntry:
        raise RuntimeError("judge unavailable")

    monkeypatch.setattr(dry_check, "_review_against_history", explode)

    with pytest.raises(RuntimeError):
        run_dry(_NO_CONTAINER, _with_repo())

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.outcome": "failed"}).count == 1
