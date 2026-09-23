"""
    Pub/sub broadcaster for review-job progress, same shape as RepoProgressBroadcaster
    but keyed by review_id: a review job terminates once, so there's no cross-instance
    relay to solve the way a repo's long-lived, resumable indexing state needs.
"""
import asyncio
import uuid

from api.schemas.reviews import ReviewAgentProgressMessage, ReviewFileProgressMessage, ReviewStatusMessage

ReviewProgressEvent = ReviewFileProgressMessage | ReviewAgentProgressMessage | ReviewStatusMessage


class ReviewProgressBroadcaster:
    """Fans out review progress events to every locally-subscribed SSE connection for that review."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[ReviewProgressEvent]]] = {}

    def subscribe(self, review_id: uuid.UUID) -> asyncio.Queue[ReviewProgressEvent]:
        queue: asyncio.Queue[ReviewProgressEvent] = asyncio.Queue()
        self._subscribers.setdefault(review_id, set()).add(queue)
        return queue

    def unsubscribe(self, review_id: uuid.UUID, queue: asyncio.Queue[ReviewProgressEvent]) -> None:
        subscribers = self._subscribers.get(review_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            del self._subscribers[review_id]

    async def publish(self, review_id: uuid.UUID, event: ReviewProgressEvent) -> None:
        for queue in list(self._subscribers.get(review_id, set())):
            await queue.put(event)
