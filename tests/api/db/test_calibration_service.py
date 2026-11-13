"""
    CalibrationService against the real local Postgres, inside a rolled-back transaction.
    Requires the migrations to have been applied (`alembic upgrade head`). Each test empties the
    calibration tables first, so nothing is persisted only because the transaction is rolled back.
"""
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.calibration.errors import NoUnlabeledPairError
from api.calibration.service import CalibrationService
from api.db.models.calibration import CalibrationLabel, CalibrationPair
from api.db.models.user import User
from api.schemas.calibration import LabelWrite

pytestmark = [pytest.mark.db, pytest.mark.asyncio]


def _pair(pair_id: str) -> CalibrationPair:
    return CalibrationPair(
        pair_id=pair_id,
        left_file_path="api/a.py",
        left_chunk_name="a",
        left_start_line=1,
        left_end_line=9,
        left_code="def a(): ...",
        right_file_path="api/b.py",
        right_chunk_name="b",
        right_start_line=1,
        right_end_line=9,
        right_code="def b(): ...",
    )


async def _user(session: AsyncSession) -> User:
    await session.execute(delete(CalibrationPair))
    user = User(
        github_id=940_000_201,
        github_username="calibration-test",
        encrypted_github_token="unused",
        github_granted_scopes="repo",
    )
    session.add(user)
    await session.flush()
    return user


async def test_labeling_skips_the_pair_and_relabeling_updates_it(async_session: AsyncSession) -> None:
    user = await _user(async_session)
    async_session.add_all([_pair("first"), _pair("second")])
    await async_session.flush()
    service = CalibrationService(async_session)

    assert (await service.next_unlabeled(user.id)).pair_id == "first"
    await service.save_label("first", user.id, LabelWrite(is_duplicate=True))
    assert (await service.next_unlabeled(user.id)).pair_id == "second"
    await service.save_label("first", user.id, LabelWrite(is_duplicate=False, note="changed my mind"))

    stored = await async_session.scalar(select(func.count()).select_from(CalibrationLabel))
    assert stored == 1
    assert (await service.export(user.id))[0].is_duplicate is False
    assert (await service.progress(user.id)).labeled == 1


async def test_next_raises_when_every_pair_is_labeled(async_session: AsyncSession) -> None:
    user = await _user(async_session)
    async_session.add(_pair("only"))
    await async_session.flush()
    service = CalibrationService(async_session)
    await service.save_label("only", user.id, LabelWrite(is_duplicate=True))

    with pytest.raises(NoUnlabeledPairError):
        await service.next_unlabeled(user.id)
