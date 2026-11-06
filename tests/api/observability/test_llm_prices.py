"""
    The price book refreshes on a timer, keeps the last good price, and can never hold up or break the app.
"""
import asyncio
import threading
import time

import pytest

from api.observability.llm_prices import PriceBook
from code_reviewer.agents.llm.pricing import PriceUnavailableError, TokenPrices

MAIN_MODEL = "vendor/main"
FAST_MODEL = "vendor/fast"
FIRST = TokenPrices(input_per_token=0.000001, output_per_token=0.000004)
SECOND = TokenPrices(input_per_token=0.000002, output_per_token=0.000008)


class FakeProvider:
    """Answers fetch_token_prices from a script: a price, or the error to raise, per model, in order."""

    def __init__(self, script: dict[str, list[TokenPrices | Exception]]) -> None:
        self._script = script
        self.fetched: list[str] = []

    def fetch_token_prices(self, model_name: str) -> TokenPrices:
        self.fetched.append(model_name)
        outcome = self._script[model_name].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _book(provider: FakeProvider, refresh_seconds: int = 3600) -> PriceBook:
    return PriceBook(provider, [MAIN_MODEL, FAST_MODEL], refresh_seconds)


def test_a_model_that_was_never_priced_is_unavailable() -> None:
    """Verify asking before any refresh raises instead of returning a made-up price."""
    book = _book(FakeProvider({}))

    with pytest.raises(PriceUnavailableError):
        book.price_of(MAIN_MODEL)


@pytest.mark.asyncio
async def test_a_refresh_prices_every_model_in_use() -> None:
    """Verify the main and the fast model both get a price from one refresh."""
    book = _book(FakeProvider({MAIN_MODEL: [FIRST], FAST_MODEL: [SECOND]}))

    await book.refresh()

    assert (book.price_of(MAIN_MODEL), book.price_of(FAST_MODEL)) == (FIRST, SECOND)


@pytest.mark.asyncio
async def test_a_model_listed_twice_is_asked_for_once() -> None:
    """Verify a deployment whose fast tier is the main model does not fetch the same price twice."""
    provider = FakeProvider({MAIN_MODEL: [FIRST]})

    await PriceBook(provider, [MAIN_MODEL, MAIN_MODEL], 3600).refresh()

    assert provider.fetched == [MAIN_MODEL]


@pytest.mark.asyncio
async def test_a_failed_refresh_keeps_the_last_good_price() -> None:
    """Verify a provider outage later on leaves the earlier price in place."""
    book = _book(FakeProvider({MAIN_MODEL: [FIRST, PriceUnavailableError("down")], FAST_MODEL: [SECOND, SECOND]}))
    await book.refresh()

    await book.refresh()

    assert book.price_of(MAIN_MODEL) == FIRST


@pytest.mark.asyncio
async def test_one_model_failing_does_not_stop_the_others_from_refreshing() -> None:
    """Verify the good model is stored even though the model before it failed."""
    book = _book(FakeProvider({MAIN_MODEL: [PriceUnavailableError("not listed")], FAST_MODEL: [SECOND]}))

    await book.refresh()

    assert book.price_of(FAST_MODEL) == SECOND


@pytest.mark.asyncio
async def test_an_unexpected_error_from_a_provider_is_contained() -> None:
    """Verify a bug in a provider adapter, not only a PriceUnavailableError, cannot escape the refresh."""
    book = _book(FakeProvider({MAIN_MODEL: [RuntimeError("adapter bug")], FAST_MODEL: [SECOND]}))

    await book.refresh()

    assert book.price_of(FAST_MODEL) == SECOND


@pytest.mark.asyncio
async def test_starting_the_book_returns_at_once_even_when_the_provider_blocks() -> None:
    """Verify app startup never waits for a price, because the first refresh runs in the background."""
    release = threading.Event()

    class BlockingProvider:
        def fetch_token_prices(self, model_name: str) -> TokenPrices:
            release.wait(timeout=5)
            return FIRST

    book = PriceBook(BlockingProvider(), [MAIN_MODEL], 3600)
    started = time.perf_counter()

    book.start()
    elapsed = time.perf_counter() - started
    release.set()
    await book.stop()

    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_the_loop_keeps_refreshing_after_a_failure() -> None:
    """Verify one bad cycle does not end the timer, so a later cycle can recover."""
    provider = FakeProvider({MAIN_MODEL: [RuntimeError("down"), FIRST]})
    book = PriceBook(provider, [MAIN_MODEL], 0)

    book.start()
    await _wait_until(lambda: len(provider.fetched) >= 2)
    await book.stop()

    assert book.price_of(MAIN_MODEL) == FIRST


@pytest.mark.asyncio
async def test_stopping_a_book_that_never_started_does_nothing() -> None:
    """Verify shutdown is safe when startup skipped the book."""
    await _book(FakeProvider({})).stop()


async def _wait_until(condition, timeout_seconds: float = 2.0) -> None:
    """Yields to the loop until the condition holds, so the test never sleeps for a guessed time."""
    deadline = time.perf_counter() + timeout_seconds
    while not condition():
        assert time.perf_counter() < deadline, "the condition was not met in time"
        await asyncio.sleep(0.01)
