import json
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.ingestion.parsing.base import ParserError
from app.ingestion.parsing.isolation import run_isolated

pytestmark = pytest.mark.unit


def test_child_environment_excludes_service_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbidden = {"DATABASE_URL", "S3_SECRET_ACCESS_KEY", "REDIS_URL", "HF_TOKEN"}
    for name in forbidden:
        monkeypatch.setenv(name, "synthetic-sensitive-value")
    output = tmp_path / "environment.json"
    run_isolated(
        "tests.parser_probe",
        ["environment", str(output)],
        timeout_seconds=5,
        memory_bytes=1024**3,
        offline=True,
    )
    environment = json.loads(output.read_text())
    assert not forbidden & environment.keys()
    assert environment["HF_HUB_OFFLINE"] == "1"


def test_noisy_child_cannot_block_and_logs_only_a_bounded_tail() -> None:
    with capture_logs() as logs, pytest.raises(ParserError) as error:
        run_isolated("tests.parser_probe", ["noisy"], timeout_seconds=5, memory_bytes=1024**3)
    assert error.value.code == "parser_failed"
    assert "END-OF-DIAGNOSTIC" not in str(error.value)
    assert "END-OF-DIAGNOSTIC" in logs[-1]["stderr_tail"]
    assert len(logs[-1]["stderr_tail"]) <= 2048
