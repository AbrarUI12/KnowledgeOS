"""Celery beat schedule (S20). Exactly one beat instance runs it (Compose `beat` service / one
supervisord program on the Space)."""

from typing import Any

from app.core.config import Settings


def beat_schedule(settings: Settings) -> dict[str, dict[str, Any]]:
    return {
        "ingestion-reconcile": {
            "task": "maintenance.reconcile",
            "schedule": float(settings.reconcile_interval_seconds),
            "options": {"queue": "maintenance", "expires": settings.reconcile_interval_seconds},
        },
    }
