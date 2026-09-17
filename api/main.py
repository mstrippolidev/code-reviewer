from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config.settings import get_api_settings
from api.db.engine import DatabaseEngine
from api.indexing.producer import RepoIndexProducer
from api.routers.auth import router as auth_router
from api.routers.health import router as health_router
from api.routers.repos import router as repos_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_api_settings()
    app.state.database_engine = DatabaseEngine(settings.async_database_url)
    app.state.http_client = httpx.AsyncClient(http2=True)
    app.state.kafka_producer = RepoIndexProducer(settings.kafka_bootstrap_servers, settings.kafka_repo_registered_topic)
    await app.state.kafka_producer.start()

    yield

    await app.state.kafka_producer.stop()
    await app.state.http_client.aclose()
    await app.state.database_engine.dispose()


def _register_routers(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(repos_router)


def _register_cors(app: FastAPI) -> None:
    settings = get_api_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_base_url],
        allow_methods=["*"],
        allow_headers=["*"],
    )


def create_app() -> FastAPI:
    app = FastAPI(title="My FastAPI Application", version="1.0.0", lifespan=lifespan)
    _register_routers(app)
    _register_cors(app)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
