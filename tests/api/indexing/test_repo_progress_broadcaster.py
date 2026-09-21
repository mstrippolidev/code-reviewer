"""
    Tests for RepoProgressBroadcaster: in-process pub/sub, no Kafka or SSE involved.
"""
import pytest

from api.db.models.indexed_file import IndexedFileStatus
from api.db.models.registered_repo import RepoIndexStatus
from api.indexing.repo_progress_broadcaster import RepoProgressBroadcaster
from api.schemas.repos import RepoFileProgressMessage, RepoStatusProgressMessage


def _file_event(repo_id: int) -> RepoFileProgressMessage:
    return RepoFileProgressMessage(
        repo_id=repo_id, file_path="main.py", status=IndexedFileStatus.INDEXED, status_reason=None
    )


def _status_event(repo_id: int) -> RepoStatusProgressMessage:
    return RepoStatusProgressMessage(repo_id=repo_id, status=RepoIndexStatus.COMPLETED, status_reason=None)


@pytest.mark.asyncio
async def test_publish_delivers_event_to_a_subscribed_queue() -> None:
    broadcaster = RepoProgressBroadcaster()
    queue = broadcaster.subscribe(repo_id=10)
    event = _file_event(repo_id=10)

    await broadcaster.publish(repo_id=10, event=event)

    assert queue.get_nowait() is event


@pytest.mark.asyncio
async def test_publish_does_not_deliver_to_a_different_repos_subscriber() -> None:
    broadcaster = RepoProgressBroadcaster()
    other_repo_queue = broadcaster.subscribe(repo_id=20)

    await broadcaster.publish(repo_id=10, event=_file_event(repo_id=10))

    assert other_repo_queue.empty()


@pytest.mark.asyncio
async def test_publish_delivers_to_every_subscriber_of_the_same_repo() -> None:
    broadcaster = RepoProgressBroadcaster()
    first_queue = broadcaster.subscribe(repo_id=10)
    second_queue = broadcaster.subscribe(repo_id=10)
    event = _status_event(repo_id=10)

    await broadcaster.publish(repo_id=10, event=event)

    assert first_queue.get_nowait() is event
    assert second_queue.get_nowait() is event


@pytest.mark.asyncio
async def test_publish_to_a_repo_with_no_subscribers_does_not_raise() -> None:
    broadcaster = RepoProgressBroadcaster()

    await broadcaster.publish(repo_id=10, event=_file_event(repo_id=10))


@pytest.mark.asyncio
async def test_unsubscribe_stops_further_delivery_to_that_queue() -> None:
    broadcaster = RepoProgressBroadcaster()
    queue = broadcaster.subscribe(repo_id=10)
    broadcaster.unsubscribe(repo_id=10, queue=queue)

    await broadcaster.publish(repo_id=10, event=_file_event(repo_id=10))

    assert queue.empty()


@pytest.mark.asyncio
async def test_unsubscribe_leaves_other_subscribers_of_the_same_repo_untouched() -> None:
    broadcaster = RepoProgressBroadcaster()
    removed_queue = broadcaster.subscribe(repo_id=10)
    remaining_queue = broadcaster.subscribe(repo_id=10)
    broadcaster.unsubscribe(repo_id=10, queue=removed_queue)
    event = _file_event(repo_id=10)

    await broadcaster.publish(repo_id=10, event=event)

    assert remaining_queue.get_nowait() is event


def test_unsubscribing_the_last_subscriber_drops_the_repo_entry() -> None:
    broadcaster = RepoProgressBroadcaster()
    queue = broadcaster.subscribe(repo_id=10)

    broadcaster.unsubscribe(repo_id=10, queue=queue)

    assert 10 not in broadcaster._subscribers


def test_unsubscribe_for_an_unknown_repo_id_does_not_raise() -> None:
    broadcaster = RepoProgressBroadcaster()

    broadcaster.unsubscribe(repo_id=999, queue=broadcaster.subscribe(repo_id=10))
