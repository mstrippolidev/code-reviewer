"""
    Tests for the scoring functions: pure arithmetic over hand-built results, no model.
"""
from code_reviewer.schemas.review import Priority
from evaluation.labels import FixtureLabel
from evaluation.scoring import LabelResult, score_agent


def make_label(expected: Priority | None, also_accepted: list[Priority | None] | None = None) -> FixtureLabel:
    return FixtureLabel(
        id="label",
        fixture="shared/clean_service.py",
        path="clean_service.py",
        expected=expected,
        also_accepted=also_accepted or [],
        reason="test label",
    )


def test_label_result_accepted_rate_is_the_share_of_runs_the_label_accepts() -> None:
    """Verify 3 accepted answers out of 4 runs is a 75% accepted rate."""
    result = LabelResult(
        label=make_label(Priority.HIGH),
        highest_per_run=[Priority.HIGH, Priority.HIGH, Priority.HIGH, Priority.LOW],
    )

    assert result.accepted_rate == 0.75


def test_a_failed_run_counts_against_the_accepted_rate() -> None:
    """Verify a run that raised produced no accepted answer."""
    result = LabelResult(label=make_label(Priority.HIGH), highest_per_run=[Priority.HIGH], failed_runs=1)

    assert result.accepted_rate == 0.5


def test_a_failed_run_is_not_a_rejected_answer() -> None:
    """Verify a crash is not reported as the agent flagging a clean file."""
    result = LabelResult(label=make_label(None), highest_per_run=[None], failed_runs=1)

    assert result.rejected_rate == 0.0


def test_recall_is_the_flagged_share_over_fixtures_with_a_violation() -> None:
    """Verify an agent that flags one of two violating fixtures has 50% recall."""
    results = [
        LabelResult(label=make_label(Priority.HIGH), highest_per_run=[Priority.HIGH]),
        LabelResult(label=make_label(Priority.HIGH), highest_per_run=[None]),
    ]

    assert score_agent("agent", results).recall == 0.5


def test_false_positive_rate_is_the_rejected_share_over_clean_fixtures() -> None:
    """Verify flagging high on a clean fixture counts as a false positive."""
    results = [
        LabelResult(label=make_label(None), highest_per_run=[None]),
        LabelResult(label=make_label(None), highest_per_run=[Priority.HIGH]),
    ]

    assert score_agent("agent", results).false_positive_rate == 0.5


def test_a_tolerated_low_note_on_a_clean_fixture_is_not_a_false_positive() -> None:
    """Verify a clean label that also accepts low does not penalize a low note."""
    results = [LabelResult(label=make_label(None, [Priority.LOW]), highest_per_run=[Priority.LOW])]

    assert score_agent("agent", results).false_positive_rate == 0.0


def test_recall_is_undefined_when_the_run_held_no_violating_fixture() -> None:
    """Verify a clean-only subset reports no recall instead of inventing one."""
    results = [LabelResult(label=make_label(None), highest_per_run=[None])]

    assert score_agent("agent", results).recall is None


def test_exact_priority_rate_counts_only_the_ideal_answer() -> None:
    """Verify an accepted alternative is not an exact match."""
    results = [
        LabelResult(label=make_label(Priority.MEDIUM, [Priority.HIGH]), highest_per_run=[Priority.MEDIUM, Priority.HIGH]),
    ]

    assert score_agent("agent", results).exact_priority_rate == 0.5
