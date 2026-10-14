"""Compose configuration (review #38): every embedding setting reaches the background worker, so
it embeds with exactly the configuration the API records on new index generations. Reads the file
only; nothing is started."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config import Settings

pytestmark = pytest.mark.unit
COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def services() -> dict[str, Any]:
    loaded = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    found: dict[str, Any] = loaded["services"]
    return found


@pytest.mark.parametrize("service", ["worker", "dispatcher", "beat"])
def test_every_embedding_setting_is_forwarded(service: str) -> None:
    environment = services()[service]["environment"]
    names = sorted(name.upper() for name in Settings.model_fields if name.startswith("embedding_"))

    assert names  # the settings exist
    for name in names:
        assert name in environment, f"{name} missing from {service}"
        # Taken from the host/.env with a default, never hard-coded.
        assert str(environment[name]).startswith(f"${{{name}"), environment[name]
    assert environment["HF_HOME"] == "/models/hf"
