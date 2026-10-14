"""Chunk ACL materialization (S23, ADR-004 layer 3).

Every chunk carries `access_principals`, the tokens of everyone who may read it, computed from
the KB's visibility and ACL and the document's own ACL (`effective_access_principals`). Retrieval
matches them against the caller's tokens (`principal_tokens`) inside the search SQL.

The tokens name principals, not people: `group:<id>` and `role:<key>` stay valid when membership
or roles change, because the caller's tokens are computed per request. Only a KB visibility, KB
ACL or document ACL change rewrites chunks, through the `acl.changed` event → `sync_knowledge_base`.

Ordering: INDEXING and the sync both hold the KB row `FOR SHARE` while they read ACLs and write
tokens, and every ACL change holds it `FOR UPDATE` (`load_kb(manage=True)`). So an ACL change
waits for an in-flight indexing transaction, and its own sync runs after both and wins.
"""

import uuid
from collections import defaultdict
from typing import Any, cast

from sqlalchemy import CursorResult, Update, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.kb_access import AclRule, effective_access_principals
from app.db.models import Chunk, Document, DocumentAcl, KnowledgeBase, KnowledgeBaseAcl
from app.domain.enums import AclPermission, PrincipalType, Visibility


async def _rewrite(session: AsyncSession, statement: Update) -> int:
    result = cast(CursorResult[Any], await session.execute(statement))
    return int(result.rowcount)


def _rule(row: KnowledgeBaseAcl | DocumentAcl) -> AclRule:
    return AclRule(
        PrincipalType(row.principal_type), row.principal_id, AclPermission(row.permission)
    )


async def _lock_kb(session: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase | None:
    return await session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update(read=True)
    )


async def _kb_rules(session: AsyncSession, kb_id: uuid.UUID) -> list[AclRule]:
    rows = await session.scalars(
        select(KnowledgeBaseAcl).where(KnowledgeBaseAcl.knowledge_base_id == kb_id)
    )
    return [_rule(row) for row in rows]


async def _document_rules(
    session: AsyncSession, kb_id: uuid.UUID, document_id: uuid.UUID | None = None
) -> dict[uuid.UUID, list[AclRule]]:
    query = (
        select(DocumentAcl)
        .join(Document, Document.id == DocumentAcl.document_id)
        .where(Document.knowledge_base_id == kb_id)
    )
    if document_id is not None:
        query = query.where(DocumentAcl.document_id == document_id)
    rules: dict[uuid.UUID, list[AclRule]] = defaultdict(list)
    for row in await session.scalars(query):
        rules[row.document_id].append(_rule(row))
    return rules


async def document_principals(
    session: AsyncSession, organization_id: uuid.UUID, kb_id: uuid.UUID, document_id: uuid.UUID
) -> list[str]:
    """The tokens for one document's chunks. Locks the KB row (shared) until the caller's
    transaction ends, so no ACL change can slip in between this read and the chunk write."""
    kb = await _lock_kb(session, kb_id)
    if kb is None:
        return []  # KB gone: nothing may read the chunks
    document_rules = await _document_rules(session, kb_id, document_id)
    return effective_access_principals(
        organization_id,
        Visibility(kb.visibility),
        await _kb_rules(session, kb_id),
        document_rules.get(document_id, []),
    )


async def sync_knowledge_base(
    session: AsyncSession, organization_id: uuid.UUID, kb_id: uuid.UUID
) -> int:
    """Re-materialize every chunk of the KB (all generations) after an ACL or visibility change,
    then stamp `acl_propagated_at`. Returns the number of chunks rewritten; chunks that already
    carry the right tokens are left alone, so a repeated sync is cheap and idempotent."""
    kb = await _lock_kb(session, kb_id)
    if kb is None:
        return 0
    visibility = Visibility(kb.visibility)
    kb_rules = await _kb_rules(session, kb_id)
    per_document = await _document_rules(session, kb_id)
    default = effective_access_principals(organization_id, visibility, kb_rules)

    rewritten = 0
    inherited = update(Chunk).where(
        Chunk.knowledge_base_id == kb_id, Chunk.access_principals.is_distinct_from(default)
    )
    if per_document:
        inherited = inherited.where(Chunk.document_id.not_in(list(per_document)))
    rewritten += await _rewrite(session, inherited.values(access_principals=default))
    for document_id, rules in sorted(per_document.items()):
        principals = effective_access_principals(organization_id, visibility, kb_rules, rules)
        rewritten += await _rewrite(
            session,
            update(Chunk)
            .where(
                Chunk.document_id == document_id,
                Chunk.access_principals.is_distinct_from(principals),
            )
            .values(access_principals=principals),
        )
    kb.acl_propagated_at = await session.scalar(select(func.now()))
    return rewritten
