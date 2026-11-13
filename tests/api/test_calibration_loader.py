"""
    Tests that the calibration pair loader inserts only new pairs, in file order, against a fake session.
"""
import asyncio
import json
from pathlib import Path

from api.calibration.pair_loader import load_pairs, read_pair_records
from api.db.models.calibration import CalibrationPair


class FakeSession:
    def __init__(self, known_pair_ids: list[str]) -> None:
        self._known_pair_ids = known_pair_ids
        self.added: list[CalibrationPair] = []
        self.commits = 0

    async def scalars(self, _statement) -> list[str]:
        return self._known_pair_ids

    def add(self, row: CalibrationPair) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


def _entry(pair_id: str) -> dict:
    side = {"file_path": "api/a.py", "chunk_name": "f", "start_line": 1, "end_line": 9, "code": "def f(): ..."}
    return {"pair_id": pair_id, "left": side, "right": side}


def _records(tmp_path: Path, pair_ids: list[str]):
    path = tmp_path / "pairs.json"
    path.write_text(json.dumps([_entry(pair_id) for pair_id in pair_ids]))
    return read_pair_records(path)


def test_only_new_pairs_are_added_in_file_order(tmp_path: Path) -> None:
    session = FakeSession(known_pair_ids=["b"])

    added = asyncio.run(load_pairs(session, _records(tmp_path, ["a", "b", "c"])))  # type: ignore[arg-type]

    assert added == 2
    assert [row.pair_id for row in session.added] == ["a", "c"]
    assert session.commits == 1


def test_a_repeated_pair_id_in_one_file_is_added_once(tmp_path: Path) -> None:
    session = FakeSession(known_pair_ids=[])

    added = asyncio.run(load_pairs(session, _records(tmp_path, ["a", "a"])))  # type: ignore[arg-type]

    assert added == 1
