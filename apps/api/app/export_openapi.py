"""Export the OpenAPI contract: `uv run python -m app.export_openapi [output_path]`.

Default output: packages/contracts/openapi.json (input for the frontend's generated TS client).
The output is deterministic (sorted keys, stable indentation) so diffs show real contract changes.
`tests/test_openapi_contract.py` fails if the committed file is out of date: run `make openapi`.
"""

import json
import sys
from pathlib import Path
from typing import Any

from app.core.config import Environment, Settings
from app.main import create_app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    # Settings without .env: the contract must not depend on a developer's environment.
    app = create_app(Settings.model_validate({"environment": Environment.TEST}))
    return app.openapi()


def render(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(build_openapi()), encoding="utf-8", newline="\n")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
