"""Verify `make demo-corpus` regenerates byte-identical files (Task T4.5).

The demo corpus is committed to the repo and consumed by retrieval, ingestion and
evaluation tests, so regeneration must be deterministic: two runs, taken a
wall-clock gap apart, must produce identical bytes. The gap is longer than the
2-second granularity of ZIP entry timestamps, so any embedded wall-clock value
would make the two runs differ — a determinism regression then fails loudly
instead of accidentally matching within the same second.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import pytest

# `pythonpath = ["."]` only exposes apps/api; the generators live in the repo-root
# `scripts` package, so put the repo root on sys.path before importing them.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

# mypy resolves `scripts` differently per platform (import-not-found on CI Linux,
# import-untyped on Windows), so the ignore has no code bracket to stay valid on both.
from scripts.demo_corpus import generate  # type: ignore  # noqa: E402

# Longer than ZIP's 2-second DOS timestamp granularity: two runs this far apart
# would embed different timestamps if the generators were non-deterministic.
WALL_CLOCK_GAP_SECONDS = 2.6


def _sha256_tree(root: Path) -> dict[str, str]:
    """Map every file under ``root`` to its SHA-256 digest (POSIX-relative path)."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


@pytest.mark.unit
def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    """Two full corpus runs, a wall-clock gap apart, must match file-for-file."""
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"

    original_output_dir = generate.OUTPUT_DIR
    try:
        generate.main(run_a)
        time.sleep(WALL_CLOCK_GAP_SECONDS)
        generate.main(run_b)
    finally:
        generate.OUTPUT_DIR = original_output_dir

    digests_a = _sha256_tree(run_a)
    digests_b = _sha256_tree(run_b)

    assert digests_a, "first run produced no files"
    assert set(digests_a) == set(digests_b), (
        "file sets differ: "
        f"only_in_run_a={sorted(set(digests_a) - set(digests_b))}, "
        f"only_in_run_b={sorted(set(digests_b) - set(digests_a))}"
    )
    mismatched = sorted(name for name in digests_a if digests_a[name] != digests_b[name])
    assert not mismatched, f"non-deterministic files: {mismatched}"
