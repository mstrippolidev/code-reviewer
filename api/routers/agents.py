from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.agent import Agent
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session
from api.schemas.agents import AgentRead

router = APIRouter(prefix="/api/agents", tags=["Agents"])


@router.get("")
async def list_agents(
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[AgentRead]:
    result = await session.scalars(select(Agent).order_by(Agent.weight.desc(), Agent.code_key))
    return [AgentRead.model_validate(agent) for agent in result.all()]
