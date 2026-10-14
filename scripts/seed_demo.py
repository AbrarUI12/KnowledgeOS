"""Seed the local demo (Session 25, T4.6): organizations, people, groups, knowledge bases and the
synthetic corpus from T4.5, all through the public API, exactly as a real client would.

Usage (local stack: `make up-full`, `make migrate`, `make api`; workers ingest the uploads):
    uv --directory apps/api run python ../../scripts/seed_demo.py [--api URL] [--wait]
    make seed

What it builds (idempotent: existing orgs, members, groups, KBs and same-titled documents are
reused, so it can run again after a partial failure):
- **Acme Corp** (`acme`): Alice (owner), Bob (member), Hana (knowledge manager, in the HR group).
  KBs HR, Support, Engineering, Compliance (organization-wide) and **HR Confidential**
  (restricted to the HR group): documents whose manifest ACL is `group:acme:hr` go there, since
  KB-level ACLs are what the API manages today (Demo 5: Bob can't find them, Hana can).
- **Globex** (`globex`): Carol (owner), KBs HR and Support with deliberately similar documents
  (Demo 6: tenant isolation).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evals" / "fixtures" / "corpus" / "demo"

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown",
    "html": "text/html",
    "txt": "text/plain",
    "csv": "text/csv",
}
KB_NAMES = {
    "hr": "HR",
    "support": "Support",
    "engineering": "Engineering",
    "compliance": "Compliance",
}
CONFIDENTIAL_KB = "HR Confidential"


@dataclass(frozen=True)
class OrgSpec:
    name: str
    owner: str
    members: dict[str, str]  # person → role


ORGS = {
    "acme": OrgSpec("Acme Corp", "alice", {"bob": "member", "hana": "knowledge_manager"}),
    "globex": OrgSpec("Globex", "carol", {}),
}
EMAILS = {
    "alice": "alice@acme.test",
    "bob": "bob@acme.test",
    "hana": "hana@acme.test",
    "carol": "carol@globex.test",
}
TERMINAL = {"READY", "FAILED_PERMANENT", "QUARANTINED", "CANCELLED", "PENDING_APPROVAL"}

TokenFor = Callable[[str], str]
PutObject = Callable[[dict[str, Any], bytes], Awaitable[None]]


def manifest(corpus: Path = CORPUS) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads(
        (corpus / "manifest.json").read_text(encoding="utf-8")
    )
    return entries


def target_kb(entry: dict[str, Any]) -> str:
    """Manifest entry → KB name: group-restricted documents go to the restricted KB."""
    if str(entry["acl"]).startswith("group:"):
        return CONFIDENTIAL_KB
    return KB_NAMES[entry["kb"]]


async def http_put(upload: dict[str, Any], data: bytes) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(
            upload.get("method", "PUT"),
            upload["url"],
            content=data,
            headers=upload.get("headers", {}),
        )
        response.raise_for_status()


@dataclass
class Seeder:
    client: httpx.AsyncClient
    token_for: TokenFor
    put_object: PutObject = http_put
    corpus: Path = CORPUS
    log: Callable[[str], None] = print
    users: dict[str, str] = field(default_factory=dict)
    orgs: dict[str, str] = field(default_factory=dict)
    kbs: dict[tuple[str, str], str] = field(default_factory=dict)
    jobs: dict[str, str] = field(default_factory=dict)  # document title → ingestion job id

    # ------------------------------------------------------------------------- HTTP helpers

    async def call(
        self, method: str, path: str, who: str, org: str | None = None, **kwargs: Any
    ) -> Any:
        headers = {"Authorization": f"Bearer {self.token_for(who)}"}
        if org:
            headers["X-Organization-Id"] = self.orgs[org]
        response = await self.client.request(method, f"/v1{path}", headers=headers, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} as {who}: {response.status_code} {response.text}")
        return response.json() if response.content else None

    async def pages(self, path: str, who: str, org: str) -> AsyncIterator[dict[str, Any]]:
        cursor = None
        while True:
            params = {"limit": 100, **({"cursor": cursor} if cursor else {})}
            page = await self.call("GET", path, who, org, params=params)
            for item in page["items"]:
                yield item
            cursor = page.get("next_cursor")
            if not cursor:
                return

    # ------------------------------------------------------------------------- steps

    async def people(self) -> None:
        for who in EMAILS:
            me = await self.call("GET", "/me", who)  # also JIT-provisions the user
            self.users[who] = me["user"]["id"]

    async def organization(self, slug: str) -> None:
        spec = ORGS[slug]
        owner = spec.owner
        me = await self.call("GET", "/me", owner)
        mine = {m["organization_slug"]: m["organization_id"] for m in me["memberships"]}
        if slug in mine:
            self.orgs[slug] = mine[slug]
        else:
            created = await self.call(
                "POST", "/organizations", owner, json={"name": spec.name, "slug": slug}
            )
            self.orgs[slug] = created["id"]
            self.log(f"created organization {spec.name}")
        members = {
            m["user_id"]
            async for m in self.pages(f"/organizations/{self.orgs[slug]}/members", owner, slug)
        }
        for who, role in spec.members.items():
            if self.users[who] in members:
                continue
            invite = await self.call(
                "POST",
                f"/organizations/{self.orgs[slug]}/invitations",
                owner,
                slug,
                json={"email": EMAILS[who], "role": role},
            )
            token = invite["accept_url"].rsplit("/", 1)[1]
            await self.call("POST", f"/invitations/{token}/accept", who)
            self.log(f"{who} joined {spec.name} as {role}")

    async def hr_group(self) -> str:
        org = self.orgs["acme"]
        groups = {
            g["name"]: g["id"]
            async for g in self.pages(f"/organizations/{org}/groups", "alice", "acme")
        }
        group = groups.get("HR")
        if group is None:
            created = await self.call(
                "POST", f"/organizations/{org}/groups", "alice", "acme", json={"name": "HR"}
            )
            group = created["id"]
        try:
            await self.call(
                "POST",
                f"/organizations/{org}/groups/{group}/members",
                "alice",
                "acme",
                json={"user_id": self.users["hana"]},
            )
        except RuntimeError as exc:  # already a member
            if " 409 " not in str(exc):
                raise
        return str(group)

    async def knowledge_bases(self, slug: str, hr_group: str | None) -> None:
        owner = ORGS[slug].owner
        listed = await self.call("GET", "/knowledge-bases", owner, slug)
        existing = {kb["name"]: kb["id"] for kb in listed}
        wanted = {target_kb(e) for e in manifest(self.corpus) if e["org"] == slug}
        for name in sorted(wanted):
            restricted = name == CONFIDENTIAL_KB
            kb_id = existing.get(name)
            if kb_id is None:
                visibility = "restricted" if restricted else "organization"
                created = await self.call(
                    "POST",
                    "/knowledge-bases",
                    owner,
                    slug,
                    json={"name": name, "visibility": visibility},
                )
                kb_id = created["id"]
            self.kbs[(slug, name)] = kb_id
            if restricted and hr_group:
                entries = [
                    {
                        "principal_type": "user",
                        "principal_id": self.users[owner],
                        "permission": "manage",
                    },
                    {"principal_type": "group", "principal_id": hr_group, "permission": "query"},
                ]
                await self.call(
                    "PUT",
                    f"/knowledge-bases/{kb_id}/permissions",
                    owner,
                    slug,
                    json={"entries": entries},
                )

    async def documents(self, slug: str) -> None:
        owner = ORGS[slug].owner
        titles: dict[str, set[str]] = {}
        for entry in manifest(self.corpus):
            if entry["org"] != slug:
                continue
            kb_id = self.kbs[(slug, target_kb(entry))]
            if kb_id not in titles:
                titles[kb_id] = {
                    d["title"]
                    async for d in self.pages(f"/knowledge-bases/{kb_id}/documents", owner, slug)
                }
            if entry["title"] in titles[kb_id]:
                continue
            data = (self.corpus / entry["file"]).read_bytes()
            upload = await self.call(
                "POST",
                f"/knowledge-bases/{kb_id}/uploads",
                owner,
                slug,
                json={
                    "filename": entry["file"],
                    "content_type": CONTENT_TYPES[Path(entry["file"]).suffix.lstrip(".")],
                    "size_bytes": len(data),
                },
            )
            await self.put_object(upload, data)
            done = await self.call(
                "POST",
                f"/uploads/{upload['upload_id']}/complete",
                owner,
                slug,
                json={"title": entry["title"], "classification": entry["classification"]},
            )
            self.jobs[entry["title"]] = done["ingestion_job_id"]
            self.log(f"uploaded {entry['file']} → {target_kb(entry)}")

    async def run(self) -> None:
        await self.people()
        for slug in ORGS:
            await self.organization(slug)
        hr = await self.hr_group()
        for slug in ORGS:
            await self.knowledge_bases(slug, hr if slug == "acme" else None)
            await self.documents(slug)

    async def wait(self, timeout_seconds: float = 900) -> dict[str, str]:
        """Poll the uploaded documents' jobs until each settles (or the timeout)."""
        owner_of = dict.fromkeys(self.jobs, "alice")
        for entry in manifest(self.corpus):
            if entry["title"] in owner_of:
                owner_of[entry["title"]] = ORGS[entry["org"]].owner
        org_of = {ORGS[s].owner: s for s in ORGS}
        states: dict[str, str] = {}
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and len(states) < len(self.jobs):
            for title, job in self.jobs.items():
                if title in states:
                    continue
                who = owner_of[title]
                state = (await self.call("GET", f"/ingestion-jobs/{job}", who, org_of[who]))[
                    "state"
                ]
                if state in TERMINAL:
                    states[title] = state
                    self.log(f"{state:16} {title}")
            await asyncio.sleep(2)
        return states


def _get_token() -> TokenFor:
    spec = importlib.util.spec_from_file_location("get_token", ROOT / "scripts" / "get_token.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("scripts/get_token.py not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cache: dict[str, str] = {}

    def token_for(who: str) -> str:
        if who not in cache:
            cache[who] = module.get_token(who)
        return cache[who]

    return token_for


async def seed(api: str, wait: bool) -> int:
    async with httpx.AsyncClient(base_url=api, timeout=60) as client:
        seeder = Seeder(client, _get_token())
        await seeder.run()
        if wait and seeder.jobs:
            states = await seeder.wait()
            failed = {t: s for t, s in states.items() if s not in {"READY", "PENDING_APPROVAL"}}
            if failed or len(states) < len(seeder.jobs):
                print(f"not ready: {failed or 'timed out'}", file=sys.stderr)
                return 1
    print("demo seeded")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--wait", action="store_true", help="wait for ingestion to finish")
    arguments = parser.parse_args()
    return asyncio.run(seed(arguments.api, arguments.wait))


if __name__ == "__main__":
    sys.exit(main())
