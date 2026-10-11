# KnowledgeOS API

FastAPI backend and Celery workers for KnowledgeOS. See the repository root `README.md`, `session.md` and `agent.md`.

```bash
uv sync                                  # install
uv run uvicorn app.main:app --reload     # run (http://localhost:8000/health/live)
uv run pytest                            # test
```
