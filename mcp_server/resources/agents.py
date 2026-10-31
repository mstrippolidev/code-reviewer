import logging
from typing import Annotated

from httpx import AsyncClient, HTTPError, Response
from mcp.server.mcpserver.exceptions import ResourceError
from pydantic import BaseModel, Field

AGENTS_URI = "agents://"
AGENTS_PATH = "/api/agents"

logger = logging.getLogger("agents_resource")


class AgentInfo(BaseModel):
    """One review agent and the rubric it judges against."""

    code_key: str
    name: str
    weight: Annotated[float, Field(gt=0)]
    category: str
    summary: str
    checks: list[str]


class AgentsResource:
    """Exposes the review roster as an MCP resource."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def read_agents(self) -> list[AgentInfo]:
        try:
            response = await self._client.get(AGENTS_PATH)
            response.raise_for_status()
        except HTTPError as error:
            logger.error("api/ failed to list the agents", exc_info=True)
            raise ResourceError("The agent list is unavailable. Try again shortly.") from error
        return self._parse(response)

    def _parse(self, response: Response) -> list[AgentInfo]:
        try:
            return [AgentInfo.model_validate(item) for item in response.json()]
        except (ValueError, TypeError) as error:
            logger.error("api/ sent an unexpected agent list", exc_info=True)
            raise ResourceError("The agent list could not be read. Try again shortly.") from error
