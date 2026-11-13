"""
    Tests for the /api/calibration router against a fake service: no real DB.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.calibration.errors import CalibrationPairNotFoundError, NoUnlabeledPairError
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session
from api.routers.calibration import get_calibration_service
from api.routers.calibration import router as calibration_router
from api.schemas.calibration import CalibrationPairRead, CalibrationProgress, LabelExport, LabelWrite, PairSideRead

USER_ID = 5


def _side(name: str) -> PairSideRead:
    return PairSideRead(file_path=f"api/{name}.py", chunk_name=name, start_line=1, end_line=8, code="def f(): ...")


class FakeCalibrationService:
    def __init__(self, finished: bool = False, known_pair: bool = True) -> None:
        self._finished = finished
        self._known_pair = known_pair
        self.saved: list[tuple[str, int, LabelWrite]] = []

    async def next_unlabeled(self, user_id: int) -> CalibrationPairRead:
        if self._finished:
            raise NoUnlabeledPairError("done")
        return CalibrationPairRead(pair_id="abc", left=_side("one"), right=_side("two"), is_duplicate=None, note=None)

    async def get_pair(self, pair_id: str, user_id: int) -> CalibrationPairRead:
        if not self._known_pair:
            raise CalibrationPairNotFoundError(pair_id)
        return await self.next_unlabeled(user_id)

    async def save_label(self, pair_id: str, user_id: int, answer: LabelWrite) -> None:
        if not self._known_pair:
            raise CalibrationPairNotFoundError(pair_id)
        self.saved.append((pair_id, user_id, answer))

    async def progress(self, user_id: int) -> CalibrationProgress:
        return CalibrationProgress(labeled=3, total=40)

    async def export(self, user_id: int) -> list[LabelExport]:
        return [LabelExport(pair_id="abc", is_duplicate=True, note=None)]


def _build_app(service: FakeCalibrationService) -> FastAPI:
    app = FastAPI()
    app.include_router(calibration_router)
    app.dependency_overrides[get_calibration_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(id=USER_ID)
    return app


def test_next_returns_a_pair_with_nothing_that_could_anchor_the_label() -> None:
    client = TestClient(_build_app(FakeCalibrationService()))

    response = client.get("/api/calibration/next")

    assert response.status_code == 200
    assert set(response.json()) == {"pair_id", "left", "right", "is_duplicate", "note"}


def test_next_is_404_once_every_pair_is_labeled() -> None:
    client = TestClient(_build_app(FakeCalibrationService(finished=True)))

    assert client.get("/api/calibration/next").status_code == 404


def test_saving_a_label_passes_the_caller_and_the_answer_to_the_service() -> None:
    service = FakeCalibrationService()
    client = TestClient(_build_app(service))

    response = client.put("/api/calibration/pairs/abc/label", json={"is_duplicate": True, "note": "same loop"})

    assert response.status_code == 204
    assert service.saved == [("abc", USER_ID, LabelWrite(is_duplicate=True, note="same loop"))]


def test_saving_a_label_for_an_unknown_pair_is_404() -> None:
    client = TestClient(_build_app(FakeCalibrationService(known_pair=False)))

    response = client.put("/api/calibration/pairs/nope/label", json={"is_duplicate": False})

    assert response.status_code == 404


def test_a_label_without_an_answer_is_rejected() -> None:
    client = TestClient(_build_app(FakeCalibrationService()))

    assert client.put("/api/calibration/pairs/abc/label", json={"note": "x"}).status_code == 422


def test_progress_and_export_are_returned() -> None:
    client = TestClient(_build_app(FakeCalibrationService()))

    assert client.get("/api/calibration/progress").json() == {"labeled": 3, "total": 40}
    assert client.get("/api/calibration/export").json() == [{"pair_id": "abc", "is_duplicate": True, "note": None}]


def test_the_routes_require_a_login() -> None:
    app = FastAPI()
    app.include_router(calibration_router)
    app.dependency_overrides[get_db_session] = lambda: None
    client = TestClient(app)

    assert client.get("/api/calibration/next").status_code == 401
