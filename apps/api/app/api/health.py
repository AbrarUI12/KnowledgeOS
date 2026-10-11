"""Operational endpoints (unversioned): liveness and readiness probes."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.health import ReadinessReport, check_readiness

router = APIRouter(tags=["operations"])


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness: the process is up and serving requests. Checks no dependencies."""
    return {"status": "ok"}


@router.get(
    "/health/ready",
    response_model=ReadinessReport,
    responses={503: {"model": ReadinessReport, "description": "A dependency is unavailable"}},
)
async def health_ready(request: Request) -> JSONResponse:
    """Readiness: database, Redis and object storage are reachable. 503 if any is not."""
    state = request.app.state
    report = await check_readiness(
        settings=state.settings, engine=state.engine, redis=state.redis, s3=state.s3
    )
    return JSONResponse(
        status_code=200 if report.status == "ok" else 503, content=report.model_dump()
    )
