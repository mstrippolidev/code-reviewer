import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config.settings import ApiSettings, get_api_settings
from api.db.engine import DatabaseEngine
from api.dependencies import get_token_cipher
from api.exception_handlers import register_exception_handlers
from api.indexing.consumer import ConsumerDependencies, consume
from api.indexing.consumers.dlq_notifier import DlqNotifier, PrintDlqNotifier
from api.indexing.consumers.repo_file_index_consumer import RepoFileIndexConsumerDependencies
from api.indexing.consumers.repo_index_consumer import RepoIndexConsumerDependencies
from api.indexing.consumers.repo_progress_consumer import RepoProgressConsumerDependencies
from api.indexing.producer import RepoIndexProducer
from api.indexing.repo_completion_finalizer import RepoCompletionFinalizer
from api.indexing.repo_indexer import RepoIndexerDependencies
from api.indexing.repo_progress_broadcaster import RepoProgressBroadcaster
from api.integrations.github import GitHubOAuthClient, GitHubOAuthConfig
from api.logging_config import configure_logging
from api.routers.auth import router as auth_router
from api.routers.health import router as health_router
from api.routers.repos import router as repos_router
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.rag.chunk_explainer import ChunkExplainer
from code_reviewer.rag.indexer import LlamaIndexRagManager

ConsumerSpec = tuple[str, ConsumerDependencies]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_api_settings()
    app.state.database_engine = DatabaseEngine(settings.async_database_url)
    app.state.http_client = httpx.AsyncClient(http2=True)
    app.state.kafka_producer = RepoIndexProducer(settings.kafka_bootstrap_servers)
    app.state.repo_completion_finalizer = RepoCompletionFinalizer(app.state.kafka_producer)
    app.state.rag_manager = LlamaIndexRagManager(explainer=ChunkExplainer(OpenRouter()))
    app.state.repo_progress_broadcaster = RepoProgressBroadcaster()
    await app.state.kafka_producer.start()
    app.state.consumer_tasks = [
        asyncio.create_task(consume(key, dependencies))
        for key, dependencies in _build_consumer_specs(app, settings)
    ]

    yield

    for task in app.state.consumer_tasks:
        task.cancel()
    for task in app.state.consumer_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await app.state.kafka_producer.stop()
    await app.state.http_client.aclose()
    await app.state.database_engine.dispose()


def _build_consumer_specs(app: FastAPI, settings: ApiSettings) -> list[ConsumerSpec]:
    return [
        ("repo_indexing", _build_repo_index_consumer_dependencies(app, settings)),
        ("repo_indexing_dlq", PrintDlqNotifier()),
        ("repo_file_indexing", _build_repo_file_index_consumer_dependencies(app, settings)),
        ("repo_progress", RepoProgressConsumerDependencies(broadcaster=app.state.repo_progress_broadcaster)),
    ]


def _build_repo_index_consumer_dependencies(app: FastAPI, settings: ApiSettings) -> RepoIndexConsumerDependencies:
    github_config = GitHubOAuthConfig(
        client_id=settings.github_oauth_client_id,
        client_secret=settings.github_oauth_client_secret,
        redirect_uri=settings.github_oauth_redirect_uri,
    )
    indexer_dependencies = RepoIndexerDependencies(
        database_engine=app.state.database_engine,
        http_client=app.state.http_client,
        token_cipher=get_token_cipher(),
        github_client=GitHubOAuthClient(github_config, app.state.http_client),
        repo_producer=app.state.kafka_producer,
        completion_finalizer=app.state.repo_completion_finalizer,
        max_concurrent_file_dispatch=settings.max_concurrent_file_dispatch,
    )
    return RepoIndexConsumerDependencies(indexer_dependencies=indexer_dependencies, dlq_producer=app.state.kafka_producer)


def _build_repo_file_index_consumer_dependencies(
    app: FastAPI, settings: ApiSettings
) -> RepoFileIndexConsumerDependencies:
    return RepoFileIndexConsumerDependencies(
        database_engine=app.state.database_engine,
        rag_manager=app.state.rag_manager,
        repo_producer=app.state.kafka_producer,
        completion_finalizer=app.state.repo_completion_finalizer,
        max_concurrent_file_indexing=settings.max_concurrent_file_indexing,
    )


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
    configure_logging(get_api_settings())
    app = FastAPI(title="My FastAPI Application", version="1.0.0", lifespan=lifespan)
    _register_routers(app)
    _register_cors(app)
    register_exception_handlers(app)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
