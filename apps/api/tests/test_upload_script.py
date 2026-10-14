"""`scripts/upload_file.py` (T2.6): presign -> PUT -> complete follows the T1.0 contract.

The upload endpoints are 501 stubs until T2.4 merges, so the flow is exercised
against an ``httpx.MockTransport`` that answers with the exact shapes from
``packages/contracts/openapi.json``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "upload_file.py"

ORG_ID = "11111111-1111-1111-1111-111111111111"
KB_ID = "22222222-2222-2222-2222-222222222222"
UPLOAD_ID = "33333333-3333-3333-3333-333333333333"
DOC_ID = "44444444-4444-4444-4444-444444444444"
VER_ID = "55555555-5555-5555-5555-555555555555"
JOB_ID = "66666666-6666-6666-6666-666666666666"
PRESIGNED_URL = "http://storage.test/quarantine/acme/eng/upload/original"


@pytest.fixture(scope="module")
def upload_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("upload_file_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
@pytest.mark.parametrize(
    ("api", "local"),
    [
        ("http://localhost:8000", True),
        ("http://127.0.0.1:8200", True),
        ("http://[::1]:8000", True),
        ("https://knowledgeos.us.auth0.com", False),
        ("http://localhost.evil.com", False),
        ("https://127.0.0.1.nip.io", False),
    ],
)
def test_only_local_api_bases_are_allowed(upload_script: ModuleType, api: str, local: bool) -> None:
    assert upload_script.is_local_api(api) is local


@pytest.mark.unit
def test_describe_error_reads_the_error_envelope(upload_script: ModuleType) -> None:
    resp = httpx.Response(
        422,
        json={"error": {"code": "file_too_large", "message": "declared size exceeds the limit"}},
    )
    assert upload_script.describe_error(resp) == "file_too_large: declared size exceeds the limit"


@pytest.mark.unit
def test_describe_error_falls_back_to_status_and_body(upload_script: ModuleType) -> None:
    resp = httpx.Response(501, json={"error": {"code": "not_implemented", "message": "stub"}})
    assert upload_script.describe_error(resp) == "not_implemented: stub"
    bare = httpx.Response(502, text="bad gateway")
    assert upload_script.describe_error(bare) == "HTTP 502: bad gateway"


@pytest.mark.unit
def test_pick_matches_slug_or_id_and_lists_alternatives(
    upload_script: ModuleType,
) -> None:
    items = [{"id": ORG_ID, "slug": "acme"}, {"id": "other", "slug": "globex"}]
    assert upload_script.pick(items, "acme", "org")["id"] == ORG_ID
    assert upload_script.pick(items, ORG_ID, "org")["slug"] == "acme"
    with pytest.raises(upload_script.UploadError, match="no org matching"):
        upload_script.pick(items, "nope", "org")
    with pytest.raises(upload_script.UploadError, match="multiple orgs"):
        upload_script.pick(items, None, "org")
    assert upload_script.pick(items[:1], None, "org")["slug"] == "acme"
    with pytest.raises(upload_script.UploadError, match="no orgs visible"):
        upload_script.pick([], None, "org")


def _flow_transport(captured: list[httpx.Request]) -> httpx.MockTransport:
    """Contract-shaped answers for the whole flow, recording every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if path == "/v1/organizations":
            return httpx.Response(200, json=[{"id": ORG_ID, "name": "Acme", "slug": "acme"}])
        if path == "/v1/knowledge-bases":
            return httpx.Response(
                200,
                json=[{"id": KB_ID, "name": "Engineering", "slug": "engineering"}],
            )
        if path == f"/v1/knowledge-bases/{KB_ID}/uploads":
            return httpx.Response(
                201,
                json={
                    "upload_id": UPLOAD_ID,
                    "url": PRESIGNED_URL,
                    "expires_at": "2026-10-12T18:30:00Z",
                    "headers": {"x-amz-meta-original-filename": "report.pdf"},
                    "method": "PUT",
                },
            )
        if path == "/quarantine/acme/eng/upload/original":
            return httpx.Response(200)
        if path == f"/v1/uploads/{UPLOAD_ID}/complete":
            return httpx.Response(
                200,
                json={
                    "document_id": DOC_ID,
                    "document_version_id": VER_ID,
                    "ingestion_job_id": JOB_ID,
                    "version_number": 1,
                },
            )
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})

    return httpx.MockTransport(handler)


@pytest.mark.unit
def test_full_flow_presign_put_complete(tmp_path: Path, upload_script: ModuleType) -> None:
    payload = b"%PDF-1.4 fake report bytes"
    source = tmp_path / "report.pdf"
    source.write_bytes(payload)

    captured: list[httpx.Request] = []
    client = httpx.Client(transport=_flow_transport(captured))
    result = upload_script.run_upload(
        client,
        "http://localhost:8000",
        "test-token",
        source,
        kb_selector="engineering",
        title="Q3 report",
        classification="confidential",
    )

    assert result["document_id"] == DOC_ID
    assert result["document_version_id"] == VER_ID
    assert result["ingestion_job_id"] == JOB_ID
    assert result["version_number"] == 1
    assert result["org_slug"] == "acme"
    assert result["kb_slug"] == "engineering"

    by_path = {request.url.path: request for request in captured}
    presign = by_path[f"/v1/knowledge-bases/{KB_ID}/uploads"]
    assert presign.method == "POST"
    assert presign.headers["Authorization"] == "Bearer test-token"
    assert presign.headers["X-Organization-Id"] == ORG_ID
    assert json.loads(presign.content) == {
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size_bytes": len(payload),
    }

    put = by_path["/quarantine/acme/eng/upload/original"]
    assert put.method == "PUT"
    assert put.content == payload
    assert put.headers["x-amz-meta-original-filename"] == "report.pdf"
    assert put.headers["Content-Type"] == "application/pdf"

    complete = by_path[f"/v1/uploads/{UPLOAD_ID}/complete"]
    assert complete.headers["X-Organization-Id"] == ORG_ID
    assert len(complete.headers["Idempotency-Key"]) >= 8
    assert json.loads(complete.content) == {"title": "Q3 report", "classification": "confidential"}


@pytest.mark.unit
def test_rejected_file_surfaces_the_envelope_code(
    tmp_path: Path, upload_script: ModuleType
) -> None:
    source = tmp_path / "payload.exe"
    source.write_bytes(b"MZ")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/organizations":
            return httpx.Response(200, json=[{"id": ORG_ID, "slug": "acme"}])
        if request.url.path == "/v1/knowledge-bases":
            return httpx.Response(200, json=[{"id": KB_ID, "slug": "engineering"}])
        return httpx.Response(
            422,
            json={"error": {"code": "file_type_not_allowed", "message": "extension not allowed"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(
        upload_script.UploadError, match="file_type_not_allowed: extension not allowed"
    ):
        upload_script.run_upload(client, "http://localhost:8000", "t", source)


@pytest.mark.unit
def test_main_refuses_non_local_api(
    tmp_path: Path, upload_script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(b"x")
    rc = upload_script.main(["alice", str(source), "--api", "https://example.com"])
    assert rc == 1
    assert "not a localhost" in capsys.readouterr().err


@pytest.mark.unit
def test_main_reports_missing_and_empty_files(
    tmp_path: Path, upload_script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = upload_script.main(
        ["alice", str(tmp_path / "missing.pdf"), "--api", "http://localhost:8000"]
    )
    assert rc == 1
    assert "file not found" in capsys.readouterr().err

    empty = tmp_path / "empty.txt"
    empty.touch()
    rc = upload_script.main(["alice", str(empty), "--api", "http://localhost:8000"])
    assert rc == 1
    assert "empty" in capsys.readouterr().err
