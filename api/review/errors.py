"""
    Refusals that apply to every way of submitting a review.
"""


class ReviewSlotBusyError(Exception):
    """Raised when a user's review slot lock could not be taken in time, because their other requests are still being recorded."""

    def __init__(self) -> None:
        super().__init__("Your other review requests are still being recorded. Try again in a moment.")


class TooManyUnfinishedReviewsError(Exception):
    """Raised when a user already has as many reviews running or waiting as they are allowed at once."""

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"You already have {limit} reviews running or waiting. Wait for one to finish before starting another."
        )
