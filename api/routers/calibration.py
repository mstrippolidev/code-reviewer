from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.calibration.errors import CalibrationPairNotFoundError, NoUnlabeledPairError
from api.calibration.service import CalibrationService
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session
from api.schemas.calibration import CalibrationPairRead, CalibrationProgress, LabelExport, LabelWrite

router = APIRouter(prefix="/api/calibration", tags=["Calibration"])


def get_calibration_service(session: AsyncSession = Depends(get_db_session)) -> CalibrationService:
    return CalibrationService(session)


@router.get("/next")
async def next_pair(
    user: User = Depends(get_current_user), service: CalibrationService = Depends(get_calibration_service)
) -> CalibrationPairRead:
    """The caller's first unlabeled pair; 404 once every pair is labeled."""
    try:
        return await service.next_unlabeled(user.id)
    except NoUnlabeledPairError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Every pair is labeled") from error


@router.get("/progress")
async def progress(
    user: User = Depends(get_current_user), service: CalibrationService = Depends(get_calibration_service)
) -> CalibrationProgress:
    """How many pairs the caller has labeled out of the total."""
    return await service.progress(user.id)


@router.get("/export")
async def export_labels(
    user: User = Depends(get_current_user), service: CalibrationService = Depends(get_calibration_service)
) -> list[LabelExport]:
    """The caller's labels, for the evaluation side to read."""
    return await service.export(user.id)


@router.get("/pairs/{pair_id}")
async def get_pair(
    pair_id: str,
    user: User = Depends(get_current_user),
    service: CalibrationService = Depends(get_calibration_service),
) -> CalibrationPairRead:
    """One pair with the caller's answer, for going back to change it."""
    try:
        return await service.get_pair(pair_id, user.id)
    except CalibrationPairNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pair not found") from error


@router.put("/pairs/{pair_id}/label", status_code=status.HTTP_204_NO_CONTENT)
async def save_label(
    pair_id: str,
    answer: LabelWrite,
    user: User = Depends(get_current_user),
    service: CalibrationService = Depends(get_calibration_service),
) -> Response:
    """Stores the caller's answer for a pair, replacing an earlier one."""
    try:
        await service.save_label(pair_id, user.id, answer)
    except CalibrationPairNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pair not found") from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
