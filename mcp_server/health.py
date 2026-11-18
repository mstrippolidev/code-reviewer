from starlette.requests import Request
from starlette.responses import JSONResponse

HEALTH_PATH = "/health"


async def report_health(request: Request) -> JSONResponse:
    """Say that this process is serving requests; it does not check that api/ is reachable."""
    return JSONResponse({"status": "ok"})
