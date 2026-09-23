from pydantic import BaseModel, ConfigDict

from api.db.models.agent import AgentCategory


class AgentRead(BaseModel):
    """One review agent and the rubric it judges against, for a client explaining a code_key."""

    model_config = ConfigDict(from_attributes=True)

    code_key: str
    name: str
    weight: float
    category: AgentCategory
    summary: str
    checks: list[str]
