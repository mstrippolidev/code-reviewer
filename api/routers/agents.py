from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.agent import Agent
from api.dependencies import get_db_session, require_user_or_guest
from api.schemas.agents import AgentRead

router = APIRouter(prefix="/api/agents", tags=["Agents"])


@router.get("")
async def list_agents(
    session: AsyncSession = Depends(get_db_session),
    _identity: None = Depends(require_user_or_guest),
) -> list[AgentRead]:
    result = await session.scalars(select(Agent).order_by(Agent.weight.desc(), Agent.code_key))
    return [AgentRead.model_validate(agent) for agent in result.all()]
