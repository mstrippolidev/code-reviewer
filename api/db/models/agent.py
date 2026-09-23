"""
    ORM model for the review roster: one row per agent, describing what that
    agent checks so a client can explain a code_key without hardcoding it.
"""
from enum import Enum

from sqlalchemy import JSON, Float
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class AgentCategory(str, Enum):
    """How an agent consumes a file, which decides what it can see at review time."""

    FILE = "file"
    CHUNK = "chunk"
    RAG = "rag"


class Agent(Base):
    """One of the review agents, with the rubric it judges against."""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_key: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    weight: Mapped[float] = mapped_column(Float)
    category: Mapped[AgentCategory] = mapped_column(
        SqlEnum(
            AgentCategory,
            name="agent_category",
            inherit_schema=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    summary: Mapped[str]
    checks: Mapped[list[str]] = mapped_column(JSON)
