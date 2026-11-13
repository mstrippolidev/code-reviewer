"""
    Once per interval, makes one real model call per model tier so a broken provider path is noticed without traffic.
"""
import asyncio
import logging
from contextlib import suppress

from api.observability.metrics import AliveResult, ApiMetrics
from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.call_observer import classify_llm_error
from code_reviewer.agents.naming import NamingAgent

logger = logging.getLogger(__name__)

PROBE_FILE_PATH = "alive_check.py"
PROBE_CODE = "def add(first: int, second: int) -> int:\n    return first + second\n"


class AliveCheck:
    """Calls each distinct model tier once per interval and records whether the call came back parsed."""

    def __init__(self, llm: LLMInterface, metrics: ApiMetrics, interval_seconds: int) -> None:
        self._llm = llm
        self._metrics = metrics
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Starts the loop in the background; the first probe runs after one full interval."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stops the loop and waits for it to end."""
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def run_once(self) -> None:
        """Probes the main tier, then the fast tier unless it is the same model."""
        probed_models: set[str] = set()
        for tier, tier_llm in (("main", self._llm), ("fast", self._llm.for_fast_tier())):
            if tier_llm.model_name in probed_models:
                continue
            probed_models.add(tier_llm.model_name)
            await self._probe(tier, tier_llm)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self.run_once()

    async def _probe(self, tier: str, tier_llm: LLMInterface) -> None:
        """Any failure is logged and counted, because the check must never take the API down."""
        try:
            output = await asyncio.to_thread(self._build_agent(tier_llm).execute_agent, PROBE_CODE, PROBE_FILE_PATH)
            result = AliveResult.FAILED if output.review[0].failed else AliveResult.OK
        except Exception as error:
            logger.warning("Alive check failed tier=%s cause=%s", tier, classify_llm_error(error), exc_info=True)
            result = AliveResult.FAILED
        self._metrics.record_alive_check(tier, tier_llm.model_name, result)

    def _build_agent(self, tier_llm: LLMInterface) -> AgentBase:
        return NamingAgent(llm=tier_llm)
