"""Smoke-check the local Docker Compose stack (Session 02).

Run with `make infra-check`. Exits non-zero if any required service is unhealthy.
Reads connection settings from the repository-root `.env` (falls back to `.env.example`).
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import asyncpg
import boto3
import httpx
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for name in (".env.example", ".env"):  # .env overrides .env.example
        path = ROOT / name
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    env.update({k: v for k, v in os.environ.items() if k in env})
    return env


ENV = load_env()


def plain_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def check_postgres() -> str:
    conn = await asyncpg.connect(plain_dsn(ENV["DATABASE_MIGRATION_URL"]), timeout=5)
    try:
        exts = {r["extname"] for r in await conn.fetch("SELECT extname FROM pg_extension")}
        missing = {"vector", "pg_trgm"} - exts
        if missing:
            raise RuntimeError(f"missing extensions: {sorted(missing)}")
        roles = {
            r["rolname"]: r
            for r in await conn.fetch(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname LIKE 'knowledgeos_%'"
            )
        }
        for name in ("knowledgeos_owner", "knowledgeos_app", "knowledgeos_dispatcher"):
            if name not in roles:
                raise RuntimeError(f"missing role {name}")
        for name in ("knowledgeos_app", "knowledgeos_dispatcher"):
            if roles[name]["rolsuper"] or roles[name]["rolbypassrls"]:
                raise RuntimeError(f"{name} must be NOSUPERUSER NOBYPASSRLS")
    finally:
        await conn.close()

    app = await asyncpg.connect(plain_dsn(ENV["DATABASE_URL"]), timeout=5)
    try:
        bypass = await app.fetchval(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        if bypass:
            raise RuntimeError("runtime role can bypass RLS")
    finally:
        await app.close()
    return "extensions vector+pg_trgm, roles ok, app role cannot bypass RLS"


async def check_redis() -> str:
    def ping() -> bytes:
        with socket.create_connection(("localhost", int(ENV["REDIS_PORT"])), timeout=3) as s:
            s.sendall(b"PING\r\n")
            return s.recv(64)

    reply = await asyncio.to_thread(ping)
    if not reply.startswith(b"+PONG"):
        raise RuntimeError(f"unexpected reply {reply!r}")
    return "PONG"


async def check_minio() -> str:
    def list_buckets() -> set[str]:
        s3 = boto3.client(
            "s3",
            endpoint_url=ENV["S3_ENDPOINT_URL"],
            aws_access_key_id=ENV["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=ENV["S3_SECRET_ACCESS_KEY"],
            region_name=ENV["S3_REGION"],
            config=Config(
                s3={"addressing_style": "path"},
                connect_timeout=3,
                retries={"max_attempts": 1},
            ),
        )
        return {b["Name"] for b in s3.list_buckets()["Buckets"]}

    found = await asyncio.to_thread(list_buckets)
    wanted = {
        ENV["S3_BUCKET_QUARANTINE"],
        ENV["S3_BUCKET_TRUSTED"],
        ENV["S3_BUCKET_ARTIFACTS"],
    }
    if wanted - found:
        raise RuntimeError(f"missing buckets: {sorted(wanted - found)}")
    return f"buckets {sorted(wanted)}"


async def check_keycloak() -> str:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"{ENV['OIDC_ISSUER']}/.well-known/openid-configuration")
        resp.raise_for_status()
        issuer = resp.json()["issuer"]
        if issuer != ENV["OIDC_ISSUER"]:
            raise RuntimeError(f"issuer mismatch: {issuer}")
        token = await client.post(
            f"{ENV['OIDC_ISSUER']}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": ENV["OIDC_CLI_CLIENT_ID"],
                "username": "alice@acme.test",
                "password": "alice-dev-password",
                "scope": "openid",
            },
        )
        token.raise_for_status()
    return f"issuer {issuer}, dev login ok"


async def check_mailpit() -> str:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"http://localhost:{ENV['MAILPIT_UI_PORT']}/api/v1/info")
        resp.raise_for_status()
    return "api ok"


async def check_clamav() -> str:
    def ping() -> bytes:
        address = (ENV["CLAMAV_HOST"], int(ENV["CLAMAV_PORT"]))
        with socket.create_connection(address, timeout=3) as s:
            s.sendall(b"zPING\0")
            return s.recv(64)

    reply = await asyncio.to_thread(ping)
    if not reply.startswith(b"PONG"):
        raise RuntimeError(f"unexpected reply {reply!r}")
    return "PONG"


CHECKS: list[tuple[str, Callable[[], Awaitable[str]], bool]] = [
    ("postgres", check_postgres, True),
    ("redis", check_redis, True),
    ("minio", check_minio, True),
    ("keycloak", check_keycloak, True),
    ("mailpit", check_mailpit, True),
    ("clamav", check_clamav, False),  # only in the `full` profile
]


async def main() -> int:
    failed = False
    for name, check, required in CHECKS:
        try:
            detail = await check()
            print(f"  OK    {name:<9} {detail}")
        except Exception as exc:
            label = "FAIL" if required else "SKIP"
            failed = failed or required
            print(f"  {label:<5} {name:<9} {type(exc).__name__}: {exc}")
    print("infra-check:", "FAILED" if failed else "all required services healthy")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
