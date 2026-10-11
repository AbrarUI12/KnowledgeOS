"""KnowledgeOS API application entrypoint."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="KnowledgeOS API", version="0.1.0")

    @app.get("/health/live", tags=["operations"])
    async def health_live() -> dict[str, str]:
        """Liveness probe: the process is up and serving requests."""
        return {"status": "ok"}

    return app


app = create_app()
