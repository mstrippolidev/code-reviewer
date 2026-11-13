"""
    Who is rating a finding: the user or the guest session that was let into the review.
"""
from pydantic import BaseModel

from api.db.models.review_job import ReviewJob


class CallerIds(BaseModel):
    """Every identity the request carried; a browser may hold a login and a guest cookie at once."""

    user_id: int | None = None
    guest_session_id: int | None = None


class Rater(BaseModel):
    user_id: int | None = None
    guest_session_id: int | None = None

    @property
    def key(self) -> str:
        """One string per rater, so a single unique constraint covers users and guests."""
        return f"user:{self.user_id}" if self.user_id is not None else f"guest:{self.guest_session_id}"


def rater_for(job: ReviewJob, caller: CallerIds) -> Rater:
    """The identity that matches how the review was opened: the guest who owns a guest review, otherwise the user."""
    if job.guest_session_id is not None and job.guest_session_id == caller.guest_session_id:
        return Rater(guest_session_id=caller.guest_session_id)
    return Rater(user_id=caller.user_id)
