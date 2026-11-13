"""
    Tests the recorder's stamping rules against a fake session; the SQL itself is covered by the db tests.
"""
import copy

import pytest

from api.feedback.incident_recorder import IncidentRecorder, content_digest_of


class FakeSession:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.statements = 0
        self._next_id = 10

    def begin_nested(self) -> "FakeSession":
        return self

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def scalar(self, statement) -> int:
        self.statements += 1
        if self.fail:
            raise RuntimeError("database refused the insert")
        self._next_id += 1
        return self._next_id


def _incident(description: str, **extra) -> dict:
    return {"priority": "high", "line_position": "1-2", "description": description, "advice": "fix it", **extra}


def _entry() -> dict:
    return {"code_key": "SOLID1", "incidents": [_incident("first"), _incident("second")]}


@pytest.mark.asyncio
async def test_every_incident_of_an_entry_gets_its_own_id() -> None:
    stamped = await IncidentRecorder(FakeSession()).stamp_entry(1, "a.py", _entry())

    assert [incident["incident_id"] for incident in stamped["incidents"]] == [11, 12]


@pytest.mark.asyncio
async def test_the_entry_that_was_passed_in_is_left_untouched() -> None:
    entry = _entry()
    before = copy.deepcopy(entry)

    await IncidentRecorder(FakeSession()).stamp_entry(1, "a.py", entry)

    assert entry == before


@pytest.mark.asyncio
async def test_a_merged_result_is_stamped_per_file_and_agent() -> None:
    result = {
        "review": [
            {"file_path": "a.py", "incidents": [_incident("one", code_key="SOLID1")]},
            {"file_path": "b.py", "incidents": [_incident("two", code_key="VAR")]},
        ]
    }

    stamped = await IncidentRecorder(FakeSession()).stamp_result(1, result)

    assert [file_review["incidents"][0]["incident_id"] for file_review in stamped["review"]] == [11, 12]


@pytest.mark.asyncio
async def test_when_recording_fails_the_original_goes_out_unstamped_and_nothing_is_raised() -> None:
    entry = _entry()

    stamped = await IncidentRecorder(FakeSession(fail=True)).stamp_entry(1, "a.py", entry)

    assert stamped is entry
    assert all("incident_id" not in incident for incident in stamped["incidents"])


@pytest.mark.asyncio
async def test_an_entry_with_no_incidents_makes_no_database_call() -> None:
    session = FakeSession()

    stamped = await IncidentRecorder(session).stamp_entry(1, "a.py", {"code_key": "VAR", "incidents": []})

    assert stamped["incidents"] == [] and session.statements == 0


def test_the_digest_follows_the_lines_and_the_description_only() -> None:
    assert content_digest_of(_incident("same", advice="a")) == content_digest_of(_incident("same", advice="b"))
    assert content_digest_of(_incident("same")) != content_digest_of(_incident("different"))
    assert content_digest_of(_incident("same")) != content_digest_of({**_incident("same"), "line_position": "3-4"})
