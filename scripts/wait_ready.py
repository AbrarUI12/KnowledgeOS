"""Wait until a KnowledgeOS API reports ready (`GET /health/ready` → 200), then print the report.

    uv --directory apps/api run python ../../scripts/wait_ready.py http://localhost:7860

Used by `make space-smoke` (S32) and the staging smoke (S33). Exits 1 on timeout with the last
readiness report, which names the failing dependency without leaking connection strings.
"""

import argparse
import json
import sys
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--timeout", type=float, default=300)
    arguments = parser.parse_args()
    deadline = time.monotonic() + arguments.timeout
    last: object = "no response"
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{arguments.base_url.rstrip('/')}/health/ready", timeout=10)
            last = response.json()
            if response.status_code == 200:
                print(json.dumps(last, indent=2))
                return 0
        except (httpx.HTTPError, ValueError) as exc:
            last = type(exc).__name__
        time.sleep(5)
    print(f"not ready after {arguments.timeout:.0f}s: {json.dumps(last)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
