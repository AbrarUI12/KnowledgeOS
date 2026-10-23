"""End-to-end smoke test of a running KnowledgeOS API (S33, fast-track C3; T6.2's API part).

    # local stack (token from the dev Keycloak via scripts/get_token.py):
    uv --directory apps/api run python ../../scripts/smoke.py --api http://localhost:8000
    # staging (a token for a demo admin; never printed):
    KOS_SMOKE_TOKEN=... uv --directory apps/api run python ../../scripts/smoke.py \
        --api https://<space>.hf.space --issuer https://<tenant>.auth0.com/

Checks: liveness and readiness → OIDC discovery → /v1/me → a fresh KB → presigned upload →
ingestion reaches READY → search finds the smoke identifier → /query answers with a valid
citation (or the step reports why) → the KB is archived again. Exit code 0 only if all pass.
Tokens, presigned URLs and secrets are never printed.
"""

import argparse
import importlib.util
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
CODE = f"KOS-SMOKE-{uuid.uuid4().hex[:6].upper()}"
DOCUMENT = (
    f"# Smoke test policy\n\nThe smoke identifier is {CODE}. Remote employees receive a "
    f"home-office allowance of 450 euros per year under policy {CODE}.\n"
).encode()


class SmokeFailure(Exception):
    pass


def step(name: str) -> None:
    print(f"• {name} …", flush=True)


def ok(detail: str = "") -> None:
    print(f"  ok{f' ({detail})' if detail else ''}", flush=True)


def local_token(user: str) -> str:
    spec = importlib.util.spec_from_file_location("get_token", ROOT / "scripts" / "get_token.py")
    if spec is None or spec.loader is None:
        raise SmokeFailure("scripts/get_token.py not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.get_token(user, quiet=True))


def expect(response: httpx.Response, *codes: int) -> Any:
    if response.status_code not in codes:
        try:
            error = response.json().get("error", {})
            reason = f"{error.get('code')}: {error.get('message')}"
        except ValueError:
            reason = response.text[:200]
        raise SmokeFailure(
            f"{response.request.method} {response.request.url.path} → "
            f"{response.status_code} {reason}"
        )
    return response.json() if response.content else None


def run(api: str, token: str, issuer: str | None, timeout: float, create_org: bool) -> None:
    client = httpx.Client(base_url=api.rstrip("/"), timeout=60)
    auth = {"Authorization": f"Bearer {token}"}

    step("liveness and readiness")
    expect(client.get("/health/live"), 200)
    expect(client.get("/health/ready"), 200)  # 503 names the failing dependency
    ok()

    if issuer:
        step("OIDC discovery")
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        discovery = expect(httpx.get(url, timeout=15), 200)
        if "jwks_uri" not in discovery:
            raise SmokeFailure("discovery document has no jwks_uri")
        ok(discovery.get("issuer", ""))

    step("who am I")
    me = expect(client.get("/v1/me", headers=auth), 200)
    memberships = [m for m in me["memberships"] if "kb.create" in m["permissions"]]
    if not memberships and create_org:  # a fresh database: the smoke user founds an org
        slug = CODE.lower()
        expect(
            client.post(
                "/v1/organizations", json={"name": f"Smoke {CODE}", "slug": slug}, headers=auth
            ),
            201,
        )
        me = expect(client.get("/v1/me", headers=auth), 200)
        memberships = [m for m in me["memberships"] if "kb.create" in m["permissions"]]
    if not memberships:
        raise SmokeFailure(
            "the smoke user needs a membership that can create knowledge bases "
            "(or pass --create-org on an empty database)"
        )
    org = memberships[0]["organization_id"]
    headers = auth | {"X-Organization-Id": org}
    ok(memberships[0]["organization_slug"])

    step("create a smoke knowledge base")
    kb = expect(
        client.post("/v1/knowledge-bases", json={"name": f"Smoke {CODE}"}, headers=headers), 201
    )["id"]
    ok(kb)
    try:
        step("presigned upload")
        upload = expect(
            client.post(
                f"/v1/knowledge-bases/{kb}/uploads",
                json={
                    "filename": "smoke-policy.md",
                    "content_type": "text/markdown",
                    "size_bytes": len(DOCUMENT),
                },
                headers=headers,
            ),
            201,
        )
        put = httpx.request(
            upload.get("method", "PUT"),
            upload["url"],
            content=DOCUMENT,
            headers=upload.get("headers", {}),
            timeout=60,
        )
        if not 200 <= put.status_code < 300:
            raise SmokeFailure(f"storage PUT → {put.status_code}")
        completed = expect(
            client.post(
                f"/v1/uploads/{upload['upload_id']}/complete",
                json={"title": "Smoke test policy", "classification": "internal"},
                headers=headers,
            ),
            200,
            201,
        )
        ok(f"job {completed['ingestion_job_id']}")

        step("ingestion reaches READY")
        deadline, state = time.monotonic() + timeout, "?"
        while time.monotonic() < deadline:
            job = expect(
                client.get(f"/v1/ingestion-jobs/{completed['ingestion_job_id']}", headers=headers),
                200,
            )
            state = job["state"]
            if state == "READY":
                break
            # FAILED_RETRYABLE retries on its own; keep waiting for one of these final states.
            if state in {"FAILED_PERMANENT", "QUARANTINED", "CANCELLED", "PENDING_APPROVAL"}:
                raise SmokeFailure(f"ingestion ended in {state}: {job.get('error_detail_safe')}")
            time.sleep(5)
        else:
            raise SmokeFailure(f"ingestion still {state} after {timeout:.0f}s")
        ok()

        step(f"search finds {CODE}")
        hits = expect(
            client.post(f"/v1/knowledge-bases/{kb}/search", json={"query": CODE}, headers=headers),
            200,
        )["hits"]
        if not hits:
            raise SmokeFailure("no search hits for the smoke identifier")
        ok(f"{len(hits)} hit(s), top match {hits[0]['match_type']}")

        step("ask with a citation")
        answer = expect(
            client.post(
                f"/v1/knowledge-bases/{kb}/query",
                json={"question": f"How much is the home-office allowance under policy {CODE}?"},
                headers=headers,
                timeout=180,
            ),
            200,
        )
        if answer["abstained"] or not answer["citations"]:
            raise SmokeFailure(f"no cited answer (abstained: {answer['abstain_reason']})")
        sent = {s["chunk_id"] for s in answer["sources"]}
        if not {c["chunk_id"] for c in answer["citations"]} <= sent:
            raise SmokeFailure("a citation points outside the sources sent")
        ok(f"{answer['evidence_status']}, {len(answer['citations'])} citation(s)")
    finally:
        step("archive the smoke knowledge base")
        archived = client.delete(f"/v1/knowledge-bases/{kb}", headers=headers)
        if archived.status_code != 204:
            problem = f"archiving KB {kb} returned {archived.status_code}; archive it by hand"
            if sys.exc_info()[0] is None:  # don't mask the failure that got us here
                raise SmokeFailure(problem)
            print(f"  warning: {problem}", file=sys.stderr)
        else:
            ok()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--issuer", help="OIDC issuer to check discovery for")
    parser.add_argument("--user", default="alice", help="local dev user (when no token is given)")
    parser.add_argument("--timeout", type=float, default=600, help="seconds to wait for READY")
    parser.add_argument(
        "--create-org", action="store_true", help="found an org if the user has none"
    )
    arguments = parser.parse_args()
    token = os.environ.get("KOS_SMOKE_TOKEN") or local_token(arguments.user)
    try:
        run(arguments.api, token, arguments.issuer, arguments.timeout, arguments.create_org)
    except (SmokeFailure, httpx.HTTPError) as exc:
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        return 1
    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
