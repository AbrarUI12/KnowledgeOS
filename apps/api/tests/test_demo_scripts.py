"""Shell flow of the crash demo (review #34): the shared worker is always restored.

`docker` and `uv` are replaced by harmless stubs on PATH that only log their arguments (and the
crash-only settings they see), so nothing touches the real Docker stack.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell stubs; runs in Linux CI"),
]

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "demo_worker_crash.sh"
STUB = """#!/usr/bin/env bash
echo "{name} $* lease=${{INGESTION_LEASE_SECONDS:-unset}}" >> "$KOS_STUB_LOG"
exit {status}
"""


def run_demo(tmp_path: Path, *, uv_status: int) -> tuple[int, list[str]]:
    bin_dir, log = tmp_path / "bin", tmp_path / "calls.log"
    bin_dir.mkdir()
    for name, status in (("docker", 0), ("uv", uv_status)):
        stub = bin_dir / name
        stub.write_text(STUB.format(name=name, status=status), encoding="utf-8")
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env["KOS_STUB_LOG"] = str(log)
    result = subprocess.run(["bash", str(SCRIPT)], env=env, check=False, capture_output=True)  # noqa: S603, S607
    return result.returncode, log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("uv_status", [0, 3])
def test_worker_is_restored_with_normal_settings_and_status_kept(
    tmp_path: Path, uv_status: int
) -> None:
    status, calls = run_demo(tmp_path, uv_status=uv_status)

    assert status == uv_status  # the test's result, failure included
    assert calls[0].startswith("docker compose -f docker-compose.yml -f infra/docker/compose.crash")
    assert calls[0].endswith("lease=15")
    assert calls[1].startswith("uv --directory apps/api run pytest -m crash")
    # Restore runs last, without the fakes override and without the crash-only settings.
    assert calls[-1] == "docker compose --profile full up -d worker beat lease=unset"
