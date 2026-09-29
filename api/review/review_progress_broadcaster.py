"""
    Pub/sub broadcaster for review-job progress, same shape as RepoProgressBroadcaster
    but keyed by review_id: a review job terminates once, so there's no cross-instance
    relay to solve the way a repo's long-lived, resumable indexing state needs.
"""
import asyncio
import uuid

from api.db.models.review_job import ReviewJobStatus
from api.schemas.reviews import ReviewAgentProgressMessage, ReviewFileProgressMessage, ReviewStatusMessage

ReviewProgressEvent = ReviewFileProgressMessage | ReviewAgentProgressMessage | ReviewStatusMessage

_TERMINAL_JOB_STATUSES = frozenset({ReviewJobStatus.COMPLETED, ReviewJobStatus.FAILED})

_InFlightAgentKey = tuple[str, str]


class ReviewProgressBroadcaster:
    """Fans out review progress events to every locally-subscribed SSE connection for that review."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[ReviewProgressEvent]]] = {}
        self._in_flight_agent_events: dict[uuid.UUID, dict[_InFlightAgentKey, ReviewAgentProgressMessage]] = {}

    def subscribe(self, review_id: uuid.UUID) -> asyncio.Queue[ReviewProgressEvent]:
        queue: asyncio.Queue[ReviewProgressEvent] = asyncio.Queue()
        for event in self._in_flight_agent_events.get(review_id, {}).values():
            queue.put_nowait(event)
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
        self._track_in_flight(review_id, event)
        for queue in list(self._subscribers.get(review_id, set())):
            await queue.put(event)

    def _track_in_flight(self, review_id: uuid.UUID, event: ReviewProgressEvent) -> None:
        if isinstance(event, ReviewAgentProgressMessage):
            in_flight = self._in_flight_agent_events.setdefault(review_id, {})
            in_flight[(event.file_path, event.code_key.value)] = event
        elif isinstance(event, ReviewFileProgressMessage):
            self._evict_file(review_id, event.file_path)
        elif isinstance(event, ReviewStatusMessage) and event.status in _TERMINAL_JOB_STATUSES:
            self._in_flight_agent_events.pop(review_id, None)

    def _evict_file(self, review_id: uuid.UUID, file_path: str) -> None:
        in_flight = self._in_flight_agent_events.get(review_id)
        if in_flight is None:
            return
        for key in [key for key in in_flight if key[0] == file_path]:
            del in_flight[key]
