"""
    Pub/sub broadcaster, the idea is to handle repo progress in a dict of set of queue
    so a user can open many tab and open many SSE conection like
    {
        repo1: {queue1, queue2},
        repo:2: {queue3}...
    }
    Receive message from kafka, and later the user connect
    to the broadcast in a SSE endpoint in fastAPI
"""
import asyncio

from api.schemas.repos import RepoFileProgressMessage, RepoStatusProgressMessage

ProgressEvent = RepoFileProgressMessage | RepoStatusProgressMessage


class RepoProgressBroadcaster:
    """Fans out repo progress events to every locally-subscribed SSE connection for that repo."""

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[ProgressEvent]]] = {}

    def subscribe(self, repo_id: int) -> asyncio.Queue[ProgressEvent]:
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
        self._subscribers.setdefault(repo_id, set()).add(queue)
        return queue

    def unsubscribe(self, repo_id: int, queue: asyncio.Queue[ProgressEvent]) -> None:
        subscribers = self._subscribers.get(repo_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers: # if the set is empty deleted
            del self._subscribers[repo_id]

    async def publish(self, repo_id: int, event: ProgressEvent) -> None:
        # add the envent to the queue (all queue of this repo_id)
        for queue in list(self._subscribers.get(repo_id, set())):
            await queue.put(event)
