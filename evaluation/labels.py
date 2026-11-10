"""
    Expected answers for fixtures, read by pytest and by the evaluation runner.
"""
from typing import Self

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from code_reviewer.schemas.review import Priority
from tests.helpers import FIXTURES_DIR

LABELS_FILE_NAME = "labels.json"


class CallReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function: str
    callee: str


class FixtureLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    fixture: str
    path: str
    expected: Priority | None
    also_accepted: list[Priority | None] = []
    flagged_any_priority: bool = False
    must_cover_call: CallReference | None = None
    paired_test_fixture: str | None = None
    reason: str

    @model_validator(mode="after")
    def _reject_priority_on_an_open_priority_label(self) -> Self:
        if self.flagged_any_priority and (self.expected is not None or self.also_accepted):
            raise ValueError(f"label {self.id}: flagged_any_priority leaves expected null and also_accepted empty")
        return self

    @property
    def accepted(self) -> list[Priority | None]:
        """Every highest priority this fixture tolerates, the ideal one first."""
        if self.flagged_any_priority:
            return list(Priority)
        return [self.expected, *self.also_accepted]

    @property
    def is_clean(self) -> bool:
        """True when the ideal answer is no incident at all."""
        return self.expected is None and not self.flagged_any_priority


def load_labels(agent_folder: str) -> list[FixtureLabel]:
    """Read the labels stored beside an agent's fixtures."""
    raw = (FIXTURES_DIR / agent_folder / LABELS_FILE_NAME).read_text()
    return TypeAdapter(list[FixtureLabel]).validate_json(raw)


def label_folders() -> list[str]:
    """The agent folders under the fixtures directory that have a labels file."""
    return sorted(path.parent.name for path in FIXTURES_DIR.glob(f"*/{LABELS_FILE_NAME}"))


def load_all_labels() -> list[FixtureLabel]:
    """Read the labels of every agent folder that has a labels file."""
    return [label for folder in label_folders() for label in load_labels(folder)]
