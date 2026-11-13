"""
    Reads pairs and reads and writes one user's labels for DRY calibration.
"""
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.calibration.errors import CalibrationPairNotFoundError, NoUnlabeledPairError
from api.db.models.calibration import CalibrationLabel, CalibrationPair
from api.schemas.calibration import CalibrationPairRead, CalibrationProgress, LabelExport, LabelWrite, PairSideRead


class CalibrationService:
    """Serves pairs in their stored order and keeps at most one label per user and pair."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_unlabeled(self, user_id: int) -> CalibrationPairRead:
        """The caller's first pair without a label.

        Raises:
            NoUnlabeledPairError: If every pair already has the caller's label.
        """
        has_label = exists().where(CalibrationLabel.pair_id == CalibrationPair.id, CalibrationLabel.user_id == user_id)
        pair = await self._session.scalar(select(CalibrationPair).where(~has_label).order_by(CalibrationPair.id).limit(1))
        if pair is None:
            raise NoUnlabeledPairError("Every pair has been labeled.")
        return _to_read(pair, None)

    async def get_pair(self, pair_id: str, user_id: int) -> CalibrationPairRead:
        """One pair with the caller's answer, for stepping back to change it.

        Raises:
            CalibrationPairNotFoundError: If no pair has that id.
        """
        pair = await self._find_pair(pair_id)
        label = await self._find_label(pair.id, user_id)
        return _to_read(pair, label)

    async def save_label(self, pair_id: str, user_id: int, answer: LabelWrite) -> None:
        """Stores the caller's answer, replacing an earlier one for the same pair.

        Raises:
            CalibrationPairNotFoundError: If no pair has that id.
        """
        pair = await self._find_pair(pair_id)
        label = await self._find_label(pair.id, user_id)
        if label is None:
            self._session.add(
                CalibrationLabel(pair_id=pair.id, user_id=user_id, is_duplicate=answer.is_duplicate, note=answer.note)
            )
        else:
            label.is_duplicate = answer.is_duplicate
            label.note = answer.note
        await self._session.commit()

    async def progress(self, user_id: int) -> CalibrationProgress:
        """How many pairs the caller has labeled, out of all of them."""
        total = await self._session.scalar(select(func.count()).select_from(CalibrationPair))
        labeled = await self._session.scalar(
            select(func.count()).select_from(CalibrationLabel).where(CalibrationLabel.user_id == user_id)
        )
        return CalibrationProgress(labeled=labeled or 0, total=total or 0)

    async def export(self, user_id: int) -> list[LabelExport]:
        """The caller's labels in pair order, as the evaluation side reads them."""
        rows = await self._session.execute(
            select(CalibrationPair.pair_id, CalibrationLabel.is_duplicate, CalibrationLabel.note)
            .join(CalibrationLabel, CalibrationLabel.pair_id == CalibrationPair.id)
            .where(CalibrationLabel.user_id == user_id)
            .order_by(CalibrationPair.id)
        )
        return [LabelExport(pair_id=pair_id, is_duplicate=is_duplicate, note=note) for pair_id, is_duplicate, note in rows]

    async def _find_pair(self, pair_id: str) -> CalibrationPair:
        pair = await self._session.scalar(select(CalibrationPair).where(CalibrationPair.pair_id == pair_id))
        if pair is None:
            raise CalibrationPairNotFoundError(f"No pair {pair_id}.")
        return pair

    async def _find_label(self, pair_row_id: int, user_id: int) -> CalibrationLabel | None:
        return await self._session.scalar(
            select(CalibrationLabel).where(CalibrationLabel.pair_id == pair_row_id, CalibrationLabel.user_id == user_id)
        )


def _to_read(pair: CalibrationPair, label: CalibrationLabel | None) -> CalibrationPairRead:
    return CalibrationPairRead(
        pair_id=pair.pair_id,
        left=PairSideRead(
            file_path=pair.left_file_path,
            chunk_name=pair.left_chunk_name,
            start_line=pair.left_start_line,
            end_line=pair.left_end_line,
            code=pair.left_code,
        ),
        right=PairSideRead(
            file_path=pair.right_file_path,
            chunk_name=pair.right_chunk_name,
            start_line=pair.right_start_line,
            end_line=pair.right_end_line,
            code=pair.right_code,
        ),
        is_duplicate=label.is_duplicate if label else None,
        note=label.note if label else None,
    )
