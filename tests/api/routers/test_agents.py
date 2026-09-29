"""
    Tests for the /api/agents router against a fake session: no real DB.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.agent import Agent, AgentCategory
from api.dependencies import get_db_session, require_user_or_guest
from api.routers.agents import router as agents_router


class _ScalarsResult:
    def __init__(self, rows: list[Agent]) -> None:
        self._rows = rows

    def all(self) -> list[Agent]:
        return self._rows


class FakeAsyncSession:
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents

    async def scalars(self, _statement) -> _ScalarsResult:
        return _ScalarsResult(self._agents)


def _make_agent(code_key: str, weight: float) -> Agent:
    return Agent(
        id=1,
        code_key=code_key,
        name="Naming",
        weight=weight,
        category=AgentCategory.CHUNK,
        summary="Names that reveal intent.",
        checks=["Abbreviations", "Names that do not reveal intent"],
    )


def _build_app(session: FakeAsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_router)

    async def _fake_db_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[require_user_or_guest] = lambda: None
    return app


def test_list_agents_returns_every_agent_with_its_rubric() -> None:
    session = FakeAsyncSession([_make_agent("VAR", 1.0), _make_agent("SOLID1", 2.0)])
    client = TestClient(_build_app(session))

    response = client.get("/api/agents")

    assert response.status_code == 200
    body = response.json()
    assert {row["code_key"] for row in body} == {"VAR", "SOLID1"}
    assert body[0]["checks"] == ["Abbreviations", "Names that do not reveal intent"]
    assert body[0]["category"] == "chunk"


def test_list_agents_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(agents_router)
    app.dependency_overrides[get_db_session] = lambda: None
    client = TestClient(app)

    response = client.get("/api/agents")

    assert response.status_code == 401
