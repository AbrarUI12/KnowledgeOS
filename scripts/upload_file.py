"""Upload a file through the secure upload flow for local development (Task T2.6).

Usage:
    uv --directory apps/api run python ../../scripts/upload_file.py alice file.pdf --kb engineering

Flow (session.md S13): get a dev token (T1.8) -> list the caller's orgs and KBs ->
request a presigned PUT (`POST /v1/knowledge-bases/{kb_id}/uploads`) -> PUT the
file bytes to the quarantine bucket -> complete (`POST /v1/uploads/{upload_id}/complete`)
-> print the document / version / job IDs. Completion creates the document version,
the queued ingestion job and the outbox row against the local stack.

Like `get_token.py` this refuses non-loopback API hosts, so it can only ever talk
to a local development stack. Until T2.4 lands, the upload endpoints answer 501
(contract stub) and the script prints that error verbatim.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import mimetypes
import sys
import uuid
from pathlib import Path

import httpx

# get_token.py lives next to this script; add scripts/ to the path so the import
# works both when this file is executed directly and when a test loads it via
# importlib from another working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from get_token import ENV, get_token, is_local_issuer

# Default matches the Makefile's API_PORT; override with --api or API_URL in .env.
DEFAULT_API_URL = "http://localhost:8000"

# Contract `Classification` enum (packages/contracts/openapi.json).
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


class UploadError(Exception):
    """A step of the upload flow failed; the message is user-facing."""


def is_local_api(url: str) -> bool:
    """True only if the API base's *host* is loopback (same check as the issuer guard)."""
    return is_local_issuer(url)


def describe_error(resp: httpx.Response) -> str:
    """Render an ErrorEnvelope (or a bare body) as a one-line message."""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and "code" in error and "message" in error:
            return f"{error['code']}: {error['message']}"
    text = (resp.text or "").strip().replace("\n", " ")
    suffix = f": {text[:200]}" if text else ""
    return f"HTTP {resp.status_code}{suffix}"


def pick(items: list[dict[str, object]], selector: str | None, kind: str) -> dict[str, object]:
    """Pick one item by slug or id; with no selector only a unique list is accepted."""
    if not items:
        raise UploadError(f"no {kind}s visible to this user (is the stack seeded?)")
    if selector is None:
        if len(items) == 1:
            return items[0]
        available = ", ".join(str(item.get("slug", item.get("id", "?"))) for item in items)
        raise UploadError(f"multiple {kind}s available, pass --{kind} (one of: {available})")
    for item in items:
        if selector in (item.get("id"), item.get("slug")):
            return item
    available = ", ".join(str(item.get("slug", item.get("id", "?"))) for item in items)
    raise UploadError(f"no {kind} matching {selector!r} (available: {available})")


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    step: str,
    token: str | None = None,
    org_id: str | None = None,
    **kwargs: object,
) -> httpx.Response:
    headers: dict[str, str] = dict(kwargs.pop("headers", {}))  # type: ignore[arg-type]
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if org_id is not None:
        headers["X-Organization-Id"] = org_id
    resp = client.request(method, url, headers=headers, **kwargs)  # type: ignore[arg-type]
    if not resp.is_success:
        raise UploadError(f"{step} failed (HTTP {resp.status_code}): {describe_error(resp)}")
    return resp


def run_upload(
    client: httpx.Client,
    api_base: str,
    token: str,
    path: Path,
    *,
    org_selector: str | None = None,
    kb_selector: str | None = None,
    title: str | None = None,
    classification: str | None = None,
    document_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """Run the full flow and return the IDs (plus the org/kb that were used)."""
    orgs = _request(client, "GET", f"{api_base}/v1/organizations", "listing organizations", token)
    org = pick(orgs.json(), org_selector, "org")

    org_id = str(org["id"])
    kbs = _request(
        client,
        "GET",
        f"{api_base}/v1/knowledge-bases",
        "listing knowledge bases",
        token,
        org_id=org_id,
    )
    kb = pick(kbs.json(), kb_selector, "kb")

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    presign_body: dict[str, object] = {
        "filename": path.name,
        "content_type": content_type,
        "size_bytes": path.stat().st_size,
    }
    if document_id is not None:
        presign_body["document_id"] = document_id
    presign = _request(
        client,
        "POST",
        f"{api_base}/v1/knowledge-bases/{kb['id']}/uploads",
        "presign",
        token,
        org_id=org_id,
        json=presign_body,
    ).json()
    upload_id = str(presign["upload_id"])

    # The presigned PUT binds the declared content type; merge any headers the
    # server requires (signature) with the content type we declared above.
    put_headers: dict[str, str] = dict(presign.get("headers") or {})
    put_headers.setdefault("Content-Type", content_type)
    _request(
        client,
        presign.get("method", "PUT"),
        str(presign["url"]),
        "uploading file",
        headers=put_headers,
        content=path.read_bytes(),
    )

    complete_body: dict[str, object] = {}
    if title is not None:
        complete_body["title"] = title
    if classification is not None:
        complete_body["classification"] = classification
    key = idempotency_key or str(uuid.uuid4())
    completed = _request(
        client,
        "POST",
        f"{api_base}/v1/uploads/{upload_id}/complete",
        "completing upload",
        token,
        org_id=org_id,
        headers={"Idempotency-Key": key},
        json=complete_body,
    ).json()

    return {
        "org_id": org_id,
        "org_slug": org.get("slug"),
        "kb_id": str(kb["id"]),
        "kb_slug": kb.get("slug"),
        "upload_id": upload_id,
        "idempotency_key": key,
        "document_id": completed["document_id"],
        "document_version_id": completed["document_version_id"],
        "ingestion_job_id": completed["ingestion_job_id"],
        "version_number": completed["version_number"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upload a file through the presigned quarantine flow (local dev only).",
        epilog="Example: ... upload_file.py alice handbook.pdf --kb engineering",
    )
    parser.add_argument("username", help="dev user: alice, bob, hana, carol")
    parser.add_argument("file", type=Path, help="file to upload")
    parser.add_argument("--org", help="org slug or id (required when the user is in several orgs)")
    parser.add_argument("--kb", help="KB slug or id (required when the org has several KBs)")
    parser.add_argument("--title", help="document title (default: server uses the filename)")
    parser.add_argument("--classification", choices=CLASSIFICATIONS)
    parser.add_argument("--document-id", help="upload as a new version of this document")
    parser.add_argument(
        "--api",
        default=ENV.get("API_URL", DEFAULT_API_URL),
        help=f"API base URL (default: {DEFAULT_API_URL} or API_URL in .env)",
    )
    parser.add_argument(
        "--idempotency-key",
        help="Idempotency-Key for complete (default: a fresh UUID per run)",
    )
    args = parser.parse_args(argv)

    if not is_local_api(args.api):
        print(
            f"ERROR: --api ({args.api}) is not a localhost address. "
            "This script only talks to the local development stack.",
            file=sys.stderr,
        )
        return 1
    if not args.file.exists():
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        return 1
    if not args.file.is_file():
        print(f"ERROR: not a regular file: {args.file}", file=sys.stderr)
        return 1
    if args.file.stat().st_size == 0:
        print(f"ERROR: {args.file.name} is empty (size_bytes must be > 0)", file=sys.stderr)
        return 1

    # get_token() prints the raw token to stdout; keep stdout for our own output.
    with contextlib.redirect_stdout(io.StringIO()):
        token = get_token(args.username)

    try:
        with httpx.Client(timeout=30) as client:
            result = run_upload(
                client,
                args.api,
                token,
                args.file,
                org_selector=args.org,
                kb_selector=args.kb,
                title=args.title,
                classification=args.classification,
                document_id=args.document_id,
                idempotency_key=args.idempotency_key,
            )
    except UploadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"ERROR: request failed: {exc}", file=sys.stderr)
        return 1

    print(f"org:      {result['org_slug']} ({result['org_id']})")
    print(f"kb:       {result['kb_slug']} ({result['kb_id']})")
    print(f"upload:   {result['upload_id']}")
    print(f"idempotency-key: {result['idempotency_key']}")
    print(f"document: {result['document_id']}")
    print(f"version:  {result['document_version_id']} (number {result['version_number']})")
    print(f"job:      {result['ingestion_job_id']} (queued)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
