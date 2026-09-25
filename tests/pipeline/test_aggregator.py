"""
    Tests for Aggregator: merges per-agent AgentReviewEntry results into
    the final weighted PR report. Pure data transformation, no LLM calls.
"""
from code_reviewer.pipeline.aggregator import Aggregator
from code_reviewer.schemas.review import (
    AggregatorOutput,
    AgentReviewEntry,
    CodeKey,
    Incident,
    PrRecommendation,
    Priority,
    ReviewScope,
    SizeStatus,
    SkippedFile,
)
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile

_AGGREGATOR = Aggregator()


def _prepared_file(
    file_path: str, content: str = "x = 1\n", size_status: SizeStatus = SizeStatus.NORMAL
) -> PreparedFile:
    return PreparedFile(source_file=SubmittedFile(file_path=file_path, content=content), size_status=size_status)


def _entry(
    code_key: CodeKey, rating: int, file_path: str = "a.py", incidents: list[Incident] | None = None
) -> AgentReviewEntry:
    return AgentReviewEntry(file_path=file_path, code_key=code_key, rating=rating, incidents=incidents or [])


def _incident(priority: Priority = Priority.LOW) -> Incident:
    return Incident(priority=priority, line_position="1-1", description="issue", advice="fix it")


def _build(
    entries: list[AgentReviewEntry], prepared_files: list[PreparedFile], skipped_files: list[SkippedFile] | None = None
) -> AggregatorOutput:
    return _AGGREGATOR.build_output(entries, prepared_files, skipped_files or [])


def _review_by_file(result: AggregatorOutput) -> dict:
    return {entry.file_path: entry for entry in result.review}


# --- File rating: weighted average across the agents that reviewed it ---


def test_file_rating_is_the_agent_weighted_average() -> None:
    entries = [_entry(CodeKey.SOLID1, rating=100), _entry(CodeKey.CMT, rating=40)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].rating == 88


def test_single_agent_rating_is_used_directly() -> None:
    entries = [_entry(CodeKey.VAR, rating=73)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].rating == 73


def test_each_file_gets_its_own_rating_independent_of_other_files() -> None:
    entries = [_entry(CodeKey.VAR, rating=100, file_path="a.py"), _entry(CodeKey.VAR, rating=50, file_path="b.py")]

    result = _build(entries, [_prepared_file("a.py"), _prepared_file("b.py")])

    assert _review_by_file(result)["b.py"].rating == 50


# --- code_key: which agents actually flagged something on this file ---


def test_code_key_only_lists_agents_that_reported_an_incident() -> None:
    entries = [_entry(CodeKey.SOLID1, rating=100, incidents=[_incident()]), _entry(CodeKey.CMT, rating=100)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].code_key == [CodeKey.SOLID1]


def test_code_key_is_empty_when_no_agent_reported_an_incident() -> None:
    entries = [_entry(CodeKey.VAR, rating=100)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].code_key == []


def test_code_key_lists_multiple_agents_in_sorted_order() -> None:
    entries = [
        _entry(CodeKey.VAR, rating=90, incidents=[_incident()]),
        _entry(CodeKey.CMT, rating=90, incidents=[_incident()]),
    ]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].code_key == [CodeKey.CMT, CodeKey.VAR]


# --- incidents: merged and stamped with their originating agent ---


def test_merged_incidents_are_stamped_with_their_originating_agent() -> None:
    entries = [_entry(CodeKey.SOLID1, rating=100, incidents=[_incident()])]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].incidents[0].code_key == CodeKey.SOLID1


def test_merged_incidents_include_every_agents_incidents_on_the_file() -> None:
    entries = [
        _entry(CodeKey.VAR, rating=90, incidents=[_incident()]),
        _entry(CodeKey.CMT, rating=90, incidents=[_incident(), _incident()]),
    ]

    result = _build(entries, [_prepared_file("a.py")])

    assert len(result.review[0].incidents) == 3


def test_each_files_incidents_do_not_leak_into_another_file() -> None:
    entries = [
        _entry(CodeKey.VAR, rating=90, file_path="a.py", incidents=[_incident()]),
        _entry(CodeKey.VAR, rating=100, file_path="b.py"),
    ]

    result = _build(entries, [_prepared_file("a.py"), _prepared_file("b.py")])

    assert _review_by_file(result)["b.py"].incidents == []


# --- agents_skipped / skip_reason: a hard-limit-exceeded agent, rating 0 ---


def test_zero_rated_agent_appears_in_agents_skipped() -> None:
    entries = [_entry(CodeKey.COH, rating=0)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].agents_skipped == [CodeKey.COH]


def test_zero_rated_agent_sets_the_hard_limit_skip_reason() -> None:
    entries = [_entry(CodeKey.COH, rating=0)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].skip_reason == "file_exceeds_hard_limit"


def test_agents_skipped_is_empty_when_no_agent_returned_zero() -> None:
    entries = [_entry(CodeKey.COH, rating=100)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].agents_skipped == []


def test_skip_reason_is_none_when_no_agent_was_skipped() -> None:
    entries = [_entry(CodeKey.COH, rating=100)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.review[0].skip_reason is None


def test_multiple_zero_rated_agents_are_all_recorded_as_skipped() -> None:
    entries = [_entry(CodeKey.COH, rating=0), _entry(CodeKey.COUP, rating=0)]

    result = _build(entries, [_prepared_file("a.py")])

    assert set(result.review[0].agents_skipped) == {CodeKey.COH, CodeKey.COUP}


# --- file_lines / size_status: passed through from the prepared file ---


def test_file_lines_reflects_the_files_line_count() -> None:
    entries = [_entry(CodeKey.VAR, rating=100)]

    result = _build(entries, [_prepared_file("a.py", content="a\nb\nc\n")])

    assert result.review[0].file_lines == "1-3"


def test_size_status_is_passed_through_from_the_prepared_file() -> None:
    entries = [_entry(CodeKey.VAR, rating=100)]

    result = _build(entries, [_prepared_file("a.py", size_status=SizeStatus.SOFT_LIMIT)])

    assert result.review[0].size_status == SizeStatus.SOFT_LIMIT


# --- Meta: PR-wide counts ---


def test_total_files_in_pr_counts_reviewed_plus_skipped() -> None:
    entries = [_entry(CodeKey.VAR, rating=100)]
    skipped = [SkippedFile(file_path="huge.py", reason="file_too_large")]

    result = _build(entries, [_prepared_file("a.py")], skipped)

    assert result.meta.total_files_in_pr == 2


def test_total_files_reviewed_counts_only_reviewed_files() -> None:
    entries = [_entry(CodeKey.VAR, rating=100, file_path="a.py")]
    skipped = [SkippedFile(file_path="huge.py", reason="file_too_large")]

    result = _build(entries, [_prepared_file("a.py")], skipped)

    assert result.meta.total_files_reviewed == 1


def test_skipped_files_are_passed_through_unchanged_in_meta() -> None:
    skipped = [SkippedFile(file_path="huge.py", reason="file_too_large")]

    result = _build([], [], skipped)

    assert result.meta.skipped_files == skipped


def test_agents_run_lists_every_agent_across_the_whole_pr() -> None:
    entries = [
        _entry(CodeKey.VAR, rating=100, file_path="a.py"),
        _entry(CodeKey.CMT, rating=100, file_path="b.py"),
    ]

    result = _build(entries, [_prepared_file("a.py"), _prepared_file("b.py")])

    assert set(result.meta.agents_run) == {CodeKey.VAR, CodeKey.CMT}


def test_overall_rating_pools_every_agent_across_every_file() -> None:
    entries = [
        _entry(CodeKey.SOLID1, rating=100, file_path="a.py"),
        _entry(CodeKey.SOLID1, rating=0, file_path="b.py"),
    ]

    result = _build(entries, [_prepared_file("a.py"), _prepared_file("b.py")])

    assert result.meta.overall_rating == 50.0


def _result_with_mixed_priority_incidents() -> AggregatorOutput:
    entries = [
        _entry(
            CodeKey.SOLID1,
            rating=50,
            incidents=[_incident(Priority.CRITICAL), _incident(Priority.HIGH), _incident(Priority.MEDIUM)],
        ),
        _entry(CodeKey.CMT, rating=90, incidents=[_incident(Priority.LOW), _incident(Priority.LOW)]),
    ]
    return _build(entries, [_prepared_file("a.py")])


def test_meta_counts_critical_incidents_across_all_files() -> None:
    assert _result_with_mixed_priority_incidents().meta.critical_incidents == 1


def test_meta_counts_high_incidents_across_all_files() -> None:
    assert _result_with_mixed_priority_incidents().meta.high_incidents == 1


def test_meta_counts_medium_incidents_across_all_files() -> None:
    assert _result_with_mixed_priority_incidents().meta.medium_incidents == 1


def test_meta_counts_low_incidents_across_all_files() -> None:
    assert _result_with_mixed_priority_incidents().meta.low_incidents == 2


# --- pr_recommendation thresholds ---


def test_rating_above_85_is_approved() -> None:
    entries = [_entry(CodeKey.VAR, rating=86)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.pr_recommendation == PrRecommendation.APPROVED


def test_rating_of_exactly_85_is_not_approved() -> None:
    entries = [_entry(CodeKey.VAR, rating=85)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.pr_recommendation == PrRecommendation.NEEDS_WORK


def test_mid_range_rating_needs_work() -> None:
    entries = [_entry(CodeKey.VAR, rating=70)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.pr_recommendation == PrRecommendation.NEEDS_WORK


def test_rating_of_exactly_60_is_needs_work() -> None:
    entries = [_entry(CodeKey.VAR, rating=60)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.pr_recommendation == PrRecommendation.NEEDS_WORK


def test_rating_just_below_60_is_rejected() -> None:
    entries = [_entry(CodeKey.VAR, rating=59)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.pr_recommendation == PrRecommendation.REJECTED


def test_low_rating_is_rejected() -> None:
    entries = [_entry(CodeKey.VAR, rating=40)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.pr_recommendation == PrRecommendation.REJECTED


# --- REJECTED overrides: zero-rated agent or a critical incident wins regardless of rating ---


def test_zero_rated_agent_forces_rejection_despite_a_high_overall_rating() -> None:
    entries = [
        _entry(CodeKey.SOLID1, rating=100, file_path="a.py"),
        _entry(CodeKey.SOLID2, rating=100, file_path="a.py"),
        _entry(CodeKey.CMT, rating=0, file_path="a.py"),
    ]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.pr_recommendation == PrRecommendation.REJECTED


def test_critical_incident_forces_rejection_even_with_a_high_rating() -> None:
    entries = [_entry(CodeKey.SOLID1, rating=100, incidents=[_incident(Priority.CRITICAL)])]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.pr_recommendation == PrRecommendation.REJECTED


def test_one_rejected_file_rejects_the_whole_pr_even_if_other_files_are_clean() -> None:
    entries = [
        _entry(CodeKey.COH, rating=0, file_path="bad.py"),
        _entry(CodeKey.VAR, rating=100, file_path="good.py"),
    ]

    result = _build(entries, [_prepared_file("bad.py"), _prepared_file("good.py")])

    assert result.meta.pr_recommendation == PrRecommendation.REJECTED


def test_hard_limit_takes_precedence_over_critical_incident_in_the_rejection_reason() -> None:
    entries = [
        _entry(CodeKey.COH, rating=0, file_path="a.py"),
        _entry(CodeKey.SOLID1, rating=100, file_path="a.py", incidents=[_incident(Priority.CRITICAL)]),
    ]

    result = _build(entries, [_prepared_file("a.py")])

    assert "hard limit" in result.meta.rejection_reason


# --- rejection_reason content ---


def test_rejection_reason_names_the_hard_limit_file() -> None:
    entries = [_entry(CodeKey.COH, rating=0, file_path="huge.py")]

    result = _build(entries, [_prepared_file("huge.py")])

    assert "huge.py" in result.meta.rejection_reason


def test_rejection_reason_names_the_critical_incidents_file() -> None:
    entries = [_entry(CodeKey.SOLID1, rating=100, file_path="risky.py", incidents=[_incident(Priority.CRITICAL)])]

    result = _build(entries, [_prepared_file("risky.py")])

    assert "risky.py" in result.meta.rejection_reason


def test_rejection_reason_mentions_the_rating_when_rejected_for_low_rating() -> None:
    entries = [_entry(CodeKey.VAR, rating=40)]

    result = _build(entries, [_prepared_file("a.py")])

    assert "40" in result.meta.rejection_reason


def test_rejection_reason_is_none_when_approved() -> None:
    entries = [_entry(CodeKey.VAR, rating=100)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.rejection_reason is None


def test_rejection_reason_is_none_when_needs_work() -> None:
    entries = [_entry(CodeKey.VAR, rating=70)]

    result = _build(entries, [_prepared_file("a.py")])

    assert result.meta.rejection_reason is None


# --- Empty submission: nothing to review, nothing wrong to report ---


def test_empty_submission_produces_no_review_entries() -> None:
    result = _build([], [])

    assert result.review == []


def test_empty_submission_defaults_overall_rating_to_100() -> None:
    result = _build([], [])

    assert result.meta.overall_rating == 100.0


def test_empty_submission_with_nothing_skipped_counts_zero_files_in_pr() -> None:
    result = _build([], [])

    assert result.meta.total_files_in_pr == 0


def test_empty_submission_is_approved() -> None:
    result = _build([], [])

    assert result.meta.pr_recommendation == PrRecommendation.APPROVED


def test_file_entry_carries_the_prepared_files_review_scope() -> None:
    """Verify review_scope passes through so a client can tell a standalone test review apart."""
    prepared = PreparedFile(
        source_file=SubmittedFile(file_path="tests/test_a.py", content="x = 1\n"),
        size_status=SizeStatus.NORMAL,
        review_scope=ReviewScope.TEST_FILE_STANDALONE,
    )

    result = _build([_entry(CodeKey.VAR, 100, file_path="tests/test_a.py")], [prepared])

    assert result.review[0].review_scope == ReviewScope.TEST_FILE_STANDALONE
