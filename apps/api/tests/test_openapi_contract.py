"""The committed OpenAPI contract (packages/contracts/openapi.json) must match the code.

If this fails after an API change: run `make openapi` and commit the result (the frontend's TS
client is generated from that file).
"""

import pytest

from app.export_openapi import DEFAULT_OUTPUT, build_openapi, render

pytestmark = pytest.mark.unit


def test_committed_openapi_matches_code() -> None:
    assert DEFAULT_OUTPUT.exists(), "packages/contracts/openapi.json missing: run `make openapi`"
    committed = DEFAULT_OUTPUT.read_text(encoding="utf-8")
    assert committed == render(build_openapi()), "OpenAPI contract is stale: run `make openapi`"


def test_operation_ids_are_unique_and_stable() -> None:
    spec = build_openapi()
    ids = [op["operationId"] for path in spec["paths"].values() for op in path.values()]
    assert len(ids) == len(set(ids))
    assert "me_get_me" in ids
    assert "query_query_knowledge_base_stream" in ids


def test_every_v1_operation_documents_the_error_envelope() -> None:
    spec = build_openapi()
    for path, ops in spec["paths"].items():
        if not path.startswith("/v1/"):
            continue
        for op in ops.values():
            assert "501" in op["responses"], f"{path} missing 501 response"
