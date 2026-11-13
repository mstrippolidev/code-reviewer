"""
    Tests for the /api/reviews/{id}/feedback router against a fake service: no real DB.
"""
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.finding_feedback import FeedbackReason, FeedbackVerdict
from api.db.models.review_job import ReviewJob
from api.dependencies import get_caller_ids, require_review_access
from api.feedback.errors import IncidentNotFoundError
from api.feedback.rater import CallerIds, Rater
from api.routers.feedback import get_feedback_service
from api.routers.feedback import router as feedback_router
from api.schemas.feedback import FeedbackRead, FeedbackWrite

REVIEW_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


class FakeFeedbackService:
    def __init__(self, known_incident: bool = True) -> None:
        self._known_incident = known_incident
        self.submitted: list[tuple[Rater, FeedbackWrite]] = []

    async def submit(self, job: ReviewJob, rater: Rater, write: FeedbackWrite) -> FeedbackRead:
        if not self._known_incident:
            raise IncidentNotFoundError("no such incident")
        self.submitted.append((rater, write))
        return FeedbackRead(incident_id=write.incident_id, verdict=write.verdict, reason=write.reason, note=write.note)

    async def list_for(self, job: ReviewJob, rater: Rater) -> list[FeedbackRead]:
        return [FeedbackRead(incident_id=4, verdict=FeedbackVerdict.UP, reason=None, note=None)]


def _build_app(service: FakeFeedbackService, job: ReviewJob, caller: CallerIds) -> FastAPI:
    app = FastAPI()
    app.include_router(feedback_router)
    app.dependency_overrides[get_feedback_service] = lambda: service
    app.dependency_overrides[require_review_access] = lambda: job
    app.dependency_overrides[get_caller_ids] = lambda: caller
    return app


def _repo_job() -> ReviewJob:
    return ReviewJob(id=1, review_id=REVIEW_ID, repo_id=10, requested_by_user_id=5, file_paths=[])


def _put(client: TestClient, **body) -> object:
    return client.put(f"/api/reviews/{REVIEW_ID}/feedback", json=body)


def test_a_thumbs_down_with_a_reason_is_stored_for_the_calling_user() -> None:
    service = FakeFeedbackService()
    client = TestClient(_build_app(service, _repo_job(), CallerIds(user_id=5)))

    response = _put(client, incident_id=7, verdict="down", reason="not_true", note="used elsewhere")

    assert response.status_code == 200
    assert response.json() == {"incident_id": 7, "verdict": "down", "reason": "not_true", "note": "used elsewhere"}
    rater, write = service.submitted[0]
    assert rater.key == "user:5" and write.reason is FeedbackReason.NOT_TRUE


def test_a_guest_rates_as_the_guest_who_owns_the_review() -> None:
    service = FakeFeedbackService()
    job = ReviewJob(id=2, review_id=REVIEW_ID, guest_session_id=3, file_paths=[])
    client = TestClient(_build_app(service, job, CallerIds(guest_session_id=3)))

    _put(client, incident_id=7, verdict="up")

    assert service.submitted[0][0].key == "guest:3"


def test_a_reason_with_a_thumbs_up_is_refused() -> None:
    client = TestClient(_build_app(FakeFeedbackService(), _repo_job(), CallerIds(user_id=5)))

    assert _put(client, incident_id=7, verdict="up", reason="not_true").status_code == 422


def test_a_reason_outside_the_list_is_refused() -> None:
    client = TestClient(_build_app(FakeFeedbackService(), _repo_job(), CallerIds(user_id=5)))

    assert _put(client, incident_id=7, verdict="down", reason="i_dislike_it").status_code == 422


def test_a_note_over_the_limit_is_refused() -> None:
    client = TestClient(_build_app(FakeFeedbackService(), _repo_job(), CallerIds(user_id=5)))

    assert _put(client, incident_id=7, verdict="down", note="x" * 501).status_code == 422


def test_an_incident_of_another_review_is_404() -> None:
    client = TestClient(_build_app(FakeFeedbackService(known_incident=False), _repo_job(), CallerIds(user_id=5)))

    assert _put(client, incident_id=99, verdict="up").status_code == 404


def test_the_callers_own_ratings_can_be_listed() -> None:
    client = TestClient(_build_app(FakeFeedbackService(), _repo_job(), CallerIds(user_id=5)))

    response = client.get(f"/api/reviews/{REVIEW_ID}/feedback")

    assert response.json() == [{"incident_id": 4, "verdict": "up", "reason": None, "note": None}]


def test_both_routes_are_guarded_by_the_review_access_check() -> None:
    for route in feedback_router.routes:
        guards = {dependency.call for dependency in route.dependant.dependencies}
        assert require_review_access in guards
