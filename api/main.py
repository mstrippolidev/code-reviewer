from fastapi import FastAPI

from api.routers.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="My FastAPI Application", version="1.0.0")
    app.include_router(health_router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)