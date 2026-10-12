"""Knowledge-base lifecycle and permissions (S12, T2.1).

Visibility decisions use app.auth.kb_access (pure, property-tested). Mutations write one audit row
in the same transaction; permission or visibility changes also emit an `acl.changed` outbox event
so chunk ACLs are re-materialized (Session 23).
"""

import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import Forbidden, InvalidPrincipal, NotFound
from app.auth.authorization import RequestContext
from app.auth.kb_access import AclRule, can_manage, can_view
from app.db.base import new_uuid
from app.db.models import (
    DataSource,
    Document,
    Group,
    KnowledgeBase,
    KnowledgeBaseAcl,
    Membership,
    Role,
)
from app.domain.enums import AclPermission, DocumentStatus, PrincipalType, Visibility
from app.domain.schemas.knowledge import (
    AclEntry,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBasePermissions,
    KnowledgeBaseUpdate,
)
from app.services import audit, outbox

_NOT_FOUND = "The knowledge base was not found."


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:55].strip("-")
    return slug or "kb"


def _rule(row: KnowledgeBaseAcl) -> AclRule:
    return AclRule(
        PrincipalType(row.principal_type), row.principal_id, AclPermission(row.permission)
    )


async def _acl_by_kb(
    session: AsyncSession, ctx: RequestContext, kb_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AclRule]]:
    rows = await session.scalars(
        select(KnowledgeBaseAcl).where(
            KnowledgeBaseAcl.organization_id == ctx.organization_id,
            KnowledgeBaseAcl.knowledge_base_id.in_(kb_ids),
        )
    )
    acl: dict[uuid.UUID, list[AclRule]] = defaultdict(list)
    for row in rows:
        acl[row.knowledge_base_id].append(_rule(row))
    return acl


async def _document_counts(
    session: AsyncSession, ctx: RequestContext, kb_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(Document.knowledge_base_id, func.count())
        .where(
            Document.organization_id == ctx.organization_id,
            Document.knowledge_base_id.in_(kb_ids),
            Document.status != DocumentStatus.DELETED.value,
        )
        .group_by(Document.knowledge_base_id)
    )
    return dict(rows.all())


def _out(kb: KnowledgeBase, acl: list[AclRule], ctx: RequestContext, docs: int) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        slug=kb.slug,
        description=kb.description,
        visibility=Visibility(kb.visibility),
        document_count=docs,
        can_manage=can_manage(ctx, acl),
        created_at=kb.created_at,
        archived_at=kb.archived_at,
    )


async def list_knowledge_bases(
    session: AsyncSession, ctx: RequestContext
) -> list[KnowledgeBaseOut]:
    """Active KBs the caller may see (query them, or manage them)."""
    kbs = list(
        await session.scalars(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.organization_id == ctx.organization_id,
                KnowledgeBase.archived_at.is_(None),
            )
            .order_by(KnowledgeBase.name, KnowledgeBase.id)
        )
    )
    ids = [kb.id for kb in kbs]
    acl = await _acl_by_kb(session, ctx, ids)
    visible = [kb for kb in kbs if can_view(ctx, Visibility(kb.visibility), acl[kb.id])]
    counts = await _document_counts(session, ctx, [kb.id for kb in visible])
    return [_out(kb, acl[kb.id], ctx, counts.get(kb.id, 0)) for kb in visible]


async def load_kb(
    session: AsyncSession, ctx: RequestContext, kb_id: uuid.UUID, *, manage: bool = False
) -> tuple[KnowledgeBase, list[AclRule]]:
    """The KB if the caller may see it (else 404); with `manage`, 403 if they may only see it.

    With `manage`, the KB row is locked FOR UPDATE *before* its ACL is read, so concurrent
    mutations (permission replacements, updates, archive) serialize and each one authorizes and
    writes against the ACL the previous one committed.
    """
    query = select(KnowledgeBase).where(
        KnowledgeBase.id == kb_id, KnowledgeBase.organization_id == ctx.organization_id
    )
    if manage:
        query = query.with_for_update()
    kb = await session.scalar(query)
    if kb is None:
        raise NotFound(_NOT_FOUND)
    acl = (await _acl_by_kb(session, ctx, [kb.id]))[kb.id]
    if not can_view(ctx, Visibility(kb.visibility), acl):
        raise NotFound(_NOT_FOUND)
    if manage and not can_manage(ctx, acl):
        raise Forbidden(
            "You can't manage this knowledge base.", details={"permission": "kb.manage"}
        )
    return kb, acl


async def get_knowledge_base(
    session: AsyncSession, ctx: RequestContext, kb_id: uuid.UUID
) -> KnowledgeBaseOut:
    kb, acl = await load_kb(session, ctx, kb_id)
    counts = await _document_counts(session, ctx, [kb.id])
    return _out(kb, acl, ctx, counts.get(kb.id, 0))


async def _unique_slug(session: AsyncSession, ctx: RequestContext, name: str) -> str:
    """Pick a free slug. A transaction-scoped advisory lock per organization serializes slug
    allocation, so two concurrent creations with the same name can't both pick `base`."""
    await session.execute(
        select(
            func.pg_advisory_xact_lock(func.hashtextextended(f"kb-slug:{ctx.organization_id}", 0))
        )
    )
    base = _slugify(name)
    taken = set(
        await session.scalars(
            select(KnowledgeBase.slug).where(
                KnowledgeBase.organization_id == ctx.organization_id,
                or_(KnowledgeBase.slug == base, KnowledgeBase.slug.like(f"{base}-%")),
            )
        )
    )
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def create_knowledge_base(
    session: AsyncSession, ctx: RequestContext, body: KnowledgeBaseCreate
) -> KnowledgeBaseOut:
    kb = KnowledgeBase(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        name=body.name,
        slug=await _unique_slug(session, ctx, body.name),
        description=body.description,
        visibility=body.visibility.value,
        created_by=ctx.user_id,
    )
    session.add(kb)
    await session.flush()
    # Every KB gets its built-in upload source (connectors add more later).
    session.add(
        DataSource(
            id=new_uuid(),
            organization_id=ctx.organization_id,
            knowledge_base_id=kb.id,
            type="upload",
            name="Uploads",
            created_by=ctx.user_id,
        )
    )
    # The creator manages what they create, so a restricted KB never starts out unreachable.
    creator = AclRule(PrincipalType.USER, str(ctx.user_id), AclPermission.MANAGE)
    session.add(_acl_row(ctx, kb.id, creator))
    await audit.record(
        session, ctx, "kb.created", "knowledge_base", kb.id, {"visibility": body.visibility.value}
    )
    await session.refresh(kb)
    return _out(kb, [creator], ctx, 0)


async def update_knowledge_base(
    session: AsyncSession, ctx: RequestContext, kb_id: uuid.UUID, body: KnowledgeBaseUpdate
) -> KnowledgeBaseOut:
    kb, acl = await load_kb(session, ctx, kb_id, manage=True)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name") is None:
        changes.pop("name", None)  # required column: null means "unchanged"
    if changes.get("visibility") is None:
        changes.pop("visibility", None)
    if "visibility" in changes:
        changes["visibility"] = Visibility(changes["visibility"]).value
    changed = {k: v for k, v in changes.items() if getattr(kb, k) != v}
    if changed:
        for field, value in changed.items():
            setattr(kb, field, value)
        kb.updated_at = datetime.now(UTC)
        await audit.record(
            session, ctx, "kb.updated", "knowledge_base", kb.id, {"fields": sorted(changed)}
        )
        if "visibility" in changed:
            await outbox.emit(
                session, ctx, "acl.changed", "knowledge_base", kb.id, {"reason": "visibility"}
            )
    counts = await _document_counts(session, ctx, [kb.id])
    return _out(kb, acl, ctx, counts.get(kb.id, 0))


async def archive_knowledge_base(
    session: AsyncSession, ctx: RequestContext, kb_id: uuid.UUID
) -> None:
    kb, _ = await load_kb(session, ctx, kb_id, manage=True)
    if kb.archived_at is not None:
        return  # already archived: idempotent, no new audit row
    kb.archived_at = datetime.now(UTC)
    await audit.record(session, ctx, "kb.archived", "knowledge_base", kb.id)


def _entries(acl: list[AclRule]) -> list[AclEntry]:
    return [
        AclEntry(
            principal_type=r.principal_type, principal_id=r.principal_id, permission=r.permission
        )
        for r in sorted(acl, key=lambda r: (r.principal_type, r.principal_id, r.permission))
    ]


async def get_permissions(
    session: AsyncSession, ctx: RequestContext, kb_id: uuid.UUID
) -> KnowledgeBasePermissions:
    kb, acl = await load_kb(session, ctx, kb_id, manage=True)
    return KnowledgeBasePermissions(entries=_entries(acl), propagated_at=kb.acl_propagated_at)


async def _validate_principals(
    session: AsyncSession, ctx: RequestContext, rules: list[AclRule]
) -> None:
    """Every principal must exist in this organization (no foreign or made-up IDs)."""
    invalid: list[str] = []
    user_ids: set[uuid.UUID] = set()
    group_ids: set[uuid.UUID] = set()
    role_keys: set[str] = set()
    for rule in rules:
        if rule.principal_type is PrincipalType.ROLE:
            role_keys.add(rule.principal_id)
            continue
        try:
            parsed = uuid.UUID(rule.principal_id)
        except ValueError:
            invalid.append(f"{rule.principal_type.value}:{rule.principal_id}")
            continue
        (user_ids if rule.principal_type is PrincipalType.USER else group_ids).add(parsed)

    members = set(
        await session.scalars(
            select(Membership.user_id).where(
                Membership.organization_id == ctx.organization_id,
                Membership.user_id.in_(user_ids),
                Membership.status == "active",
            )
        )
    )
    groups = set(
        await session.scalars(
            select(Group.id).where(
                Group.organization_id == ctx.organization_id, Group.id.in_(group_ids)
            )
        )
    )
    roles = set(
        await session.scalars(
            select(Role.key).where(
                Role.key.in_(role_keys),
                or_(Role.organization_id.is_(None), Role.organization_id == ctx.organization_id),
            )
        )
    )
    invalid += [f"user:{u}" for u in sorted(user_ids - members, key=str)]
    invalid += [f"group:{g}" for g in sorted(group_ids - groups, key=str)]
    invalid += [f"role:{r}" for r in sorted(role_keys - roles)]
    if invalid:
        raise InvalidPrincipal(details={"principals": invalid})


def _acl_row(ctx: RequestContext, kb_id: uuid.UUID, rule: AclRule) -> KnowledgeBaseAcl:
    return KnowledgeBaseAcl(
        knowledge_base_id=kb_id,
        organization_id=ctx.organization_id,
        principal_type=rule.principal_type.value,
        principal_id=rule.principal_id,
        permission=rule.permission.value,
    )


async def set_permissions(
    session: AsyncSession, ctx: RequestContext, kb_id: uuid.UUID, entries: list[AclEntry]
) -> KnowledgeBasePermissions:
    """Replace the KB's allow-only ACL (PUT semantics)."""
    kb, current = await load_kb(session, ctx, kb_id, manage=True)
    desired = sorted(
        {AclRule(e.principal_type, e.principal_id, e.permission) for e in entries},
        key=lambda r: (r.principal_type, r.principal_id, r.permission),
    )
    await _validate_principals(session, ctx, desired)
    if set(desired) == set(current):
        return KnowledgeBasePermissions(
            entries=_entries(current), propagated_at=kb.acl_propagated_at
        )

    await session.execute(
        delete(KnowledgeBaseAcl).where(
            KnowledgeBaseAcl.organization_id == ctx.organization_id,
            KnowledgeBaseAcl.knowledge_base_id == kb.id,
        )
    )
    session.add_all(_acl_row(ctx, kb.id, rule) for rule in desired)
    kb.acl_propagated_at = None  # chunks no longer reflect the ACL until Session 23 re-syncs
    await audit.record(
        session,
        ctx,
        "kb.permissions_changed",
        "knowledge_base",
        kb.id,
        {"entries": len(desired)},
    )
    await outbox.emit(session, ctx, "acl.changed", "knowledge_base", kb.id, {"reason": "acl"})
    return KnowledgeBasePermissions(entries=_entries(desired), propagated_at=None)
