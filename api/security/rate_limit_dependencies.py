from fastapi import Depends
from redis.asyncio import Redis

from api.config.settings import get_api_settings
from api.db.models.guest_session import GuestSession
from api.db.models.user import User
from api.dependencies import get_current_user, get_guest_session, get_redis
from api.security.rate_limit import RateLimiter

REPO_REGISTRATION_SCOPE = "repo_registration"
REVIEW_SUBMISSION_SCOPE = "review_submission"
GUEST_REVIEW_SUBMISSION_SCOPE = "guest_review_submission"


def get_rate_limiter(redis: Redis = Depends(get_redis)) -> RateLimiter:
    return RateLimiter(redis)


async def limit_repo_registrations(
    user: User = Depends(get_current_user),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    await limiter.hit(REPO_REGISTRATION_SCOPE, user.id, get_api_settings().max_repo_registrations_per_minute)


async def limit_review_submissions(
    user: User = Depends(get_current_user),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    await limiter.hit(REVIEW_SUBMISSION_SCOPE, user.id, get_api_settings().max_review_submissions_per_minute)


async def limit_guest_review_submissions(
    guest_session: GuestSession = Depends(get_guest_session),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    limit = get_api_settings().max_guest_review_submissions_per_minute
    await limiter.hit(GUEST_REVIEW_SUBMISSION_SCOPE, guest_session.id, limit)
