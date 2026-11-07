"""
    Keeps the last known token price of each model in use, refreshed on a timer and read without waiting.
"""
import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.pricing import PriceUnavailableError, TokenPrices

logger = logging.getLogger(__name__)


class PriceBook:
    """Holds the price of each model the deployment uses; a failed refresh keeps the last good price."""

    def __init__(self, llm: LLMInterface, model_names: Sequence[str], refresh_seconds: int) -> None:
        self._llm = llm
        self._model_names = tuple(dict.fromkeys(model_names))
        self._refresh_seconds = refresh_seconds
        self._prices: dict[str, TokenPrices] = {}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Starts refreshing in the background; the first refresh runs there too, so startup never waits for it."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stops refreshing and waits for the background task to end."""
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    def price_of(self, model_name: str) -> TokenPrices:
        """Reads the last known price from memory.

        Raises:
            PriceUnavailableError: If the model has never been priced successfully.
        """
        try:
            return self._prices[model_name]
        except KeyError as error:
            raise PriceUnavailableError(f"No price is known for {model_name}.") from error

    async def refresh(self) -> None:
        """Asks the provider for every model's price; a model that fails keeps its previous one."""
        for model_name in self._model_names:
            await self._refresh_one(model_name)

    async def _run(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(self._refresh_seconds)

    async def _refresh_one(self, model_name: str) -> None:
        """Any failure is logged, because a price problem must only ever cost the cost metric."""
        try:
            self._prices[model_name] = await asyncio.to_thread(self._llm.fetch_token_prices, model_name)
        except Exception:
            logger.warning("Could not refresh the token price of model=%s", model_name, exc_info=True)
