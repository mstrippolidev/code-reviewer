"""
    Tests for the label files: they must load and must point at fixtures that exist.
"""
import pytest

from evaluation.labels import FixtureLabel, LabelKind, label_folders, load_all_labels, load_labels
from tests.helpers import FIXTURES_DIR

ALL_LABELS = load_all_labels()


def fixtures_of(label: FixtureLabel) -> list[str]:
    return [name for name in (label.fixture, label.paired_test_fixture) if name]


@pytest.mark.parametrize("label", ALL_LABELS, ids=lambda label: label.id)
def test_label_points_at_an_existing_fixture(label: FixtureLabel) -> None:
    """Verify a label's fixtures exist, so a renamed fixture fails here and not as a silent skip."""
    assert all((FIXTURES_DIR / name).exists() for name in fixtures_of(label))


@pytest.mark.parametrize("folder", label_folders())
def test_label_ids_are_unique_within_an_agent_folder(folder: str) -> None:
    """Verify no two labels of one agent share an id, since run reports are keyed by it."""
    ids = [label.id for label in load_labels(folder)]

    assert len(ids) == len(set(ids))


def test_flagged_any_priority_with_an_expected_priority_is_rejected() -> None:
    """Verify a label cannot ask for both 'any priority' and a specific one."""
    with pytest.raises(ValueError):
        FixtureLabel(
            id="contradiction",
            fixture="complexity/priority_high.py",
            path="priority_high.py",
            expected="high",
            flagged_any_priority=True,
            reason="contradiction",
        )


def label_of_kind(kind: str | None = None) -> dict[str, str]:
    fields = {
        "id": "kind-probe",
        "fixture": "complexity/priority_high.py",
        "path": "priority_high.py",
        "expected": "high",
        "reason": "probe",
    }
    return {**fields, "kind": kind} if kind else fields


def test_a_label_without_a_kind_is_standard() -> None:
    """Verify the existing label files keep working, since kind defaults to standard."""
    label = FixtureLabel.model_validate(label_of_kind())

    assert label.kind is LabelKind.STANDARD


@pytest.mark.parametrize("kind", [LabelKind.GRAY_AREA, LabelKind.INJECTION])
def test_a_label_accepts_the_gray_area_and_injection_kinds(kind: LabelKind) -> None:
    """Verify both new kinds load from the label file's text."""
    label = FixtureLabel.model_validate(label_of_kind(kind.value))

    assert label.kind is kind


def test_an_unknown_kind_is_rejected() -> None:
    """Verify a misspelled kind fails loading instead of silently counting as standard."""
    with pytest.raises(ValueError):
        FixtureLabel.model_validate(label_of_kind("grey_area"))
