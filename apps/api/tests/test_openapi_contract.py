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


def _collect_missing_refs(node: object, components: dict[str, object], missing: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.split("/")[-1] not in components:
            missing.add(ref)
        for value in node.values():
            _collect_missing_refs(value, components, missing)
    elif isinstance(node, list):
        for value in node:
            _collect_missing_refs(value, components, missing)


def test_all_schema_references_resolve() -> None:
    spec = build_openapi()
    missing: set[str] = set()
    _collect_missing_refs(spec, spec["components"]["schemas"], missing)
    assert not missing


def test_sse_events_are_in_the_contract() -> None:
    spec = build_openapi()
    stream = spec["paths"]["/v1/knowledge-bases/{kb_id}/query/stream"]["post"]
    content = stream["responses"]["200"]["content"]["text/event-stream"]
    assert content["schema"] == {"$ref": "#/components/schemas/StreamEvent"}
    for name in (
        "StreamMeta",
        "StreamStage",
        "StreamSources",
        "StreamAnswerDelta",
        "StreamCitation",
        "StreamDone",
        "StreamError",
    ):
        assert name in spec["components"]["schemas"]


def test_idempotency_and_filter_parameters_are_declared() -> None:
    paths = build_openapi()["paths"]

    def params(path: str, method: str) -> set[str]:
        return {p["name"] for p in paths[path][method].get("parameters", [])}

    assert "Idempotency-Key" in params("/v1/organizations", "post")
    assert "Idempotency-Key" in params("/v1/uploads/{upload_id}/complete", "post")
    assert {"status", "document_type", "classification"} <= params(
        "/v1/knowledge-bases/{kb_id}/documents", "get"
    )


def test_permissions_update_does_not_accept_server_owned_fields() -> None:
    spec = build_openapi()
    body = spec["paths"]["/v1/knowledge-bases/{kb_id}/permissions"]["put"]["requestBody"]
    ref = body["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    assert "propagated_at" not in spec["components"]["schemas"][ref]["properties"]
