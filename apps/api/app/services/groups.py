"""Groups and group membership (S09, T1.3). Groups feed chunk ACL principals (`group:<id>`)."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import GroupNameTaken, NotFound
from app.auth.authorization import RequestContext
from app.db.base import new_uuid
from app.db.models import Group, GroupMembership, Membership
from app.domain.schemas.common import Page
from app.domain.schemas.identity import GroupCreate, GroupOut, GroupUpdate
from app.services import audit
from app.services.pagination import after_cursor, encode_cursor, page_limit


def _member_count() -> Any:
    return (
        select(func.count())
        .select_from(GroupMembership)
        .where(GroupMembership.group_id == Group.id)
        .scalar_subquery()
    )


async def list_groups(
    session: AsyncSession, ctx: RequestContext, *, cursor: str | None, limit: int
) -> Page[GroupOut]:
    limit = page_limit(limit)
    query = (
        select(Group, _member_count().label("member_count"))
        .where(Group.organization_id == ctx.organization_id)
        .order_by(Group.created_at, Group.id)
    )
    if (clause := after_cursor(Group.created_at, Group.id, cursor)) is not None:
        query = query.where(clause)
    rows = list((await session.execute(query.limit(limit + 1))).all())
    items = [_out(group, count) for group, count in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1][0]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page[GroupOut](items=items, next_cursor=next_cursor)


def _out(group: Group, member_count: int) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        member_count=member_count,
        created_at=group.created_at,
    )


async def ensure_group(session: AsyncSession, ctx: RequestContext, group_id: uuid.UUID) -> None:
    """404 unless the group exists in the caller's organization."""
    await _get(session, ctx, group_id)


async def _get(session: AsyncSession, ctx: RequestContext, group_id: uuid.UUID) -> Group:
    group = await session.scalar(
        select(Group).where(Group.id == group_id, Group.organization_id == ctx.organization_id)
    )
    if group is None:
        raise NotFound("The group was not found.")
    return group


async def _count(session: AsyncSession, group_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(GroupMembership)
            .where(GroupMembership.group_id == group_id)
        )
        or 0
    )


async def _flush_unique_name(session: AsyncSession) -> None:
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise GroupNameTaken from exc


async def create_group(session: AsyncSession, ctx: RequestContext, body: GroupCreate) -> GroupOut:
    group = Group(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        name=body.name,
        description=body.description,
    )
    session.add(group)
    await _flush_unique_name(session)
    await audit.record(session, ctx, "group.created", "group", group.id, {"name": body.name})
    await session.refresh(group)
    return _out(group, 0)


async def update_group(
    session: AsyncSession, ctx: RequestContext, group_id: uuid.UUID, body: GroupUpdate
) -> GroupOut:
    group = await _get(session, ctx, group_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        changes.pop("name")  # name is required; null means "unchanged"
    changed = {k: v for k, v in changes.items() if getattr(group, k) != v}
    if changed:
        for field, value in changed.items():
            setattr(group, field, value)
        await _flush_unique_name(session)
        await audit.record(
            session, ctx, "group.updated", "group", group.id, {"fields": sorted(changed)}
        )
    return _out(group, await _count(session, group.id))


async def delete_group(session: AsyncSession, ctx: RequestContext, group_id: uuid.UUID) -> None:
    group = await _get(session, ctx, group_id)
    await session.delete(group)  # group_memberships cascade (composite FK)
    await audit.record(session, ctx, "group.deleted", "group", group_id, {"name": group.name})


async def add_member(
    session: AsyncSession, ctx: RequestContext, group_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await _get(session, ctx, group_id)
    is_member = await session.scalar(
        select(Membership.id).where(
            Membership.organization_id == ctx.organization_id, Membership.user_id == user_id
        )
    )
    if is_member is None:
        raise NotFound("The member was not found.")
    inserted = await session.scalar(
        insert(GroupMembership)
        .values(group_id=group_id, user_id=user_id, organization_id=ctx.organization_id)
        .on_conflict_do_nothing()
        .returning(GroupMembership.user_id)
    )
    if inserted is not None:  # adding an existing member is a no-op, not a mutation
        await audit.record(
            session, ctx, "group.member_added", "group", group_id, {"user_id": str(user_id)}
        )


async def remove_member(
    session: AsyncSession, ctx: RequestContext, group_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await _get(session, ctx, group_id)
    row = await session.scalar(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
            GroupMembership.organization_id == ctx.organization_id,
        )
    )
    if row is None:
        raise NotFound("The member is not in this group.")
    await session.delete(row)
    await audit.record(
        session, ctx, "group.member_removed", "group", group_id, {"user_id": str(user_id)}
    )


__all__ = [
    "add_member",
    "create_group",
    "delete_group",
    "ensure_group",
    "list_groups",
    "remove_member",
    "update_group",
]
