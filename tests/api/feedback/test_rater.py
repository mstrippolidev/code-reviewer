"""
    Tests that a rating is attributed to the identity that was let into the review.
"""
import uuid

from api.db.models.review_job import ReviewJob
from api.feedback.rater import CallerIds, Rater, rater_for


def _job(**overrides) -> ReviewJob:
    return ReviewJob(id=1, review_id=uuid.uuid4(), file_paths=[], **overrides)


def test_a_user_and_a_guest_get_different_keys() -> None:
    assert Rater(user_id=5).key == "user:5"
    assert Rater(guest_session_id=3).key == "guest:3"


def test_the_guest_who_owns_a_guest_review_rates_as_that_guest() -> None:
    job = _job(guest_session_id=3)

    rater = rater_for(job, CallerIds(guest_session_id=3))

    assert rater.key == "guest:3"


def test_a_user_who_also_holds_a_guest_cookie_rates_a_repo_review_as_the_user() -> None:
    job = _job(repo_id=10, requested_by_user_id=5)

    rater = rater_for(job, CallerIds(user_id=5, guest_session_id=3))

    assert rater.key == "user:5"


def test_a_guest_cookie_that_does_not_own_the_review_is_not_used() -> None:
    job = _job(guest_session_id=9)

    rater = rater_for(job, CallerIds(user_id=5, guest_session_id=3))

    assert rater.key == "user:5"
