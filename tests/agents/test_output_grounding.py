"""
    Tests for the check that a review is about the code it was given: hand-built outputs, no model.
"""
from code_reviewer.agents.output_grounding import is_review_invented
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, Incident, Priority
from tests.helpers import load_fixture

CODE = "class Cart:\n    def __init__(self):\n        self.items = []\n\n    def add(self, item):\n        self.items.append(item)\n"


def output_with(*incidents: Incident) -> AgentOutput:
    return AgentOutput(review=[AgentReviewEntry(code_key=CodeKey.BOUND, incidents=list(incidents))])


def incident(description: str, line_position: str = "3-3") -> Incident:
    return Incident(priority=Priority.HIGH, line_position=line_position, description=description, advice="fix it")


def test_an_incident_about_code_in_the_file_is_not_invented() -> None:
    """Verify a real finding that quotes names found in the code passes."""
    review = output_with(incident("`Cart.items` is a public list that callers can mutate."))

    assert not is_review_invented(review, CODE)


def test_lines_beyond_the_end_of_the_file_are_invented() -> None:
    """Verify a well-formed range that ends after the last line counts as code that is not there."""
    review = output_with(incident("The public list is exposed.", line_position="40-60"))

    assert is_review_invented(review, CODE)


def test_a_placeholder_range_at_line_zero_is_invented() -> None:
    """Verify '0-0', seen with a filler description on a real run, is outside the file since lines start at 1."""
    review = output_with(incident("It is the descripiption", line_position="0-0"))

    assert is_review_invented(review, CODE)


def test_quoted_names_missing_from_the_file_are_invented() -> None:
    """Verify an in-range incident naming only functions that the file does not contain counts as invented."""
    review = output_with(incident("`handle_department_created` trusts `department` ids from the payload."))

    assert is_review_invented(review, CODE)


def test_half_of_the_incidents_outside_the_file_keeps_the_review() -> None:
    """Verify a review is kept when exactly half of its incidents are ungrounded, since only more than half fails."""
    review = output_with(
        incident("`handle_department_created` trusts the payload."),
        incident("`items` is public and mutable.", line_position="3-3"),
    )

    assert not is_review_invented(review, CODE)


def test_most_incidents_outside_the_file_are_invented_even_if_one_is_real() -> None:
    """Verify a review with one real incident among many outside the file counts as invented."""
    review = output_with(
        incident("The public list is exposed.", line_position="40-60"),
        incident("The public list is exposed.", line_position="70-80"),
        incident("`items` is public and mutable.", line_position="3-3"),
    )

    assert is_review_invented(review, CODE)


def test_a_malformed_line_range_is_not_evidence_of_invented_code() -> None:
    """Verify '7-0' and a bare number, formatting slips seen on real runs, do not fail a review about real code."""
    review = output_with(incident("`items` is public.", line_position="7-0"), incident("`add` leaks.", "5"))

    assert not is_review_invented(review, CODE)


def test_quoting_only_python_builtins_proves_nothing() -> None:
    """Verify a description that quotes only `None` or `list` has no names to check, so it passes."""
    review = output_with(incident("Returns `None` instead of raising, typed as `list`."))

    assert not is_review_invented(review, CODE)


def test_a_review_with_no_incidents_is_never_invented() -> None:
    """Verify an empty review is left alone, since nothing in it can be checked."""
    assert not is_review_invented(output_with(), CODE)


def test_the_name_check_can_be_switched_off_for_agents_that_read_other_files() -> None:
    """Verify an agent with a cross-file tool may quote names from files it fetched, so only lines are checked."""
    review = output_with(incident("`Session` from infrastructure leaks into the domain."))

    assert is_review_invented(review, CODE)
    assert not is_review_invented(review, CODE, checks_quoted_names=False)


TCASE_SOURCE = load_fixture("tcase/partially_tested_source.py")


def test_a_multi_incident_tcase_report_about_the_file_is_kept() -> None:
    """Verify the three-incident TCASE reply seen on a real run, about the right function, is not invented."""
    review = output_with(
        incident("The negative-value branch that raises ValueError is unasserted.", line_position="11-12"),
        incident("`calculate_total`'s multi-item accumulation path is unasserted.", line_position="10-13"),
        incident("The rounding path is unasserted.", line_position="14"),
    )

    assert not is_review_invented(review, TCASE_SOURCE)


def test_most_of_fourteen_incidents_beyond_a_short_file_are_invented() -> None:
    """Verify 14 incidents on a 16-line file, 11 of them past the last line, fails although 3 land inside it."""
    inside = [incident("The rounding path is unasserted.", line_position="9-10") for _ in range(3)]
    outside = [incident("The rounding path is unasserted.", line_position=f"{40 + n}-{41 + n}") for n in range(11)]

    assert is_review_invented(output_with(*inside, *outside), TCASE_SOURCE)
