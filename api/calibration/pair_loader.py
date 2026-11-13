"""
    Loads the pairs file built by evaluation.calibration.make_pairs into the calibration table, skipping pairs already there.
"""
import json
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.calibration import CalibrationPair
from api.schemas.calibration import PairSideRead


class PairRecord(BaseModel):
    pair_id: str
    left: PairSideRead
    right: PairSideRead


def read_pair_records(path: Path) -> list[PairRecord]:
    """Parses a pairs.json file.

    Raises:
        FileNotFoundError: If the file does not exist.
        pydantic.ValidationError: If an entry does not have the pair shape.
    """
    return [PairRecord.model_validate(entry) for entry in json.loads(path.read_text())]


async def load_pairs(session: AsyncSession, records: list[PairRecord]) -> int:
    """Inserts the records whose pair id is new, keeping their order, and returns how many were added."""
    known = set(await session.scalars(select(CalibrationPair.pair_id)))
    added = 0
    for record in records:
        if record.pair_id in known:
            continue
        session.add(_to_row(record))
        known.add(record.pair_id)
        added += 1
    await session.commit()
    return added


def _to_row(record: PairRecord) -> CalibrationPair:
    return CalibrationPair(
        pair_id=record.pair_id,
        left_file_path=record.left.file_path,
        left_chunk_name=record.left.chunk_name,
        left_start_line=record.left.start_line,
        left_end_line=record.left.end_line,
        left_code=record.left.code,
        right_file_path=record.right.file_path,
        right_chunk_name=record.right.chunk_name,
        right_start_line=record.right.start_line,
        right_end_line=record.right.end_line,
        right_code=record.right.code,
    )
