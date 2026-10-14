"""Knowledge-base and document access rules (S12, plan §7.3, ADR-004 layer 3).

Pure functions over the caller's RequestContext and allow-only ACL entries, so they can be
property-tested and reused by the search layer (which applies the same rules in SQL, Session 24).

- `organization` KB: every member with `query.execute` may query it.
- `restricted` KB: only principals on its ACL (user, group or role) may query it.
- Manage: the `kb.manage` permission, or a `manage` ACL entry. Managers can always *see* the KB
  (metadata, settings, ACL), but reading a restricted KB's *content* needs an ACL entry: chunk
  ACL tokens carry only ACL principals, so query and retrieval agree (Session 23).
- Document ACLs may only **narrow** access, never widen a restricted KB.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.auth.authorization import RequestContext, has_permission
from app.auth.permissions import Permission
from app.domain.enums import AclPermission, PrincipalType, Visibility


@dataclass(frozen=True, slots=True)
class AclRule:
    principal_type: PrincipalType
    principal_id: str
    permission: AclPermission

    @property
    def principal(self) -> tuple[PrincipalType, str]:
        return self.principal_type, self.principal_id


def caller_principals(ctx: RequestContext) -> set[tuple[PrincipalType, str]]:
    return {
        (PrincipalType.USER, str(ctx.user_id)),
        (PrincipalType.ROLE, ctx.role),
        *((PrincipalType.GROUP, str(g)) for g in ctx.group_ids),
    }


def _matches(ctx: RequestContext, acl: Iterable[AclRule], permission: AclPermission | None) -> bool:
    mine = caller_principals(ctx)
    return any(
        rule.principal in mine and (permission is None or rule.permission == permission)
        for rule in acl
    )


def can_manage(ctx: RequestContext, acl: Iterable[AclRule]) -> bool:
    return has_permission(ctx, Permission.KB_MANAGE) or _matches(ctx, acl, AclPermission.MANAGE)


def can_query(ctx: RequestContext, visibility: Visibility, acl: Iterable[AclRule]) -> bool:
    """May read the KB's content (search, ask, open documents)."""
    if not has_permission(ctx, Permission.QUERY_EXECUTE):
        return False
    if visibility is Visibility.ORGANIZATION:
        return True
    # Restricted: any ACL entry (query or manage) for one of the caller's principals.
    return _matches(ctx, acl, None)


def can_view(ctx: RequestContext, visibility: Visibility, acl: Iterable[AclRule]) -> bool:
    """May see that the KB exists (list, get). Otherwise it's 404."""
    acl = list(acl)
    return can_query(ctx, visibility, acl) or can_manage(ctx, acl)


def widening_entries(
    visibility: Visibility, kb_acl: Iterable[AclRule], document_acl: Iterable[AclRule]
) -> list[AclRule]:
    """Document ACL entries that would grant access the knowledge base doesn't (plan §7.3).

    An `organization` KB already reaches every member, so any document ACL narrows it. For a
    `restricted` KB, each document principal must itself be on the KB's ACL.
    """
    if visibility is Visibility.ORGANIZATION:
        return []
    allowed = {rule.principal for rule in kb_acl}
    return [rule for rule in document_acl if rule.principal not in allowed]


def _token(rule: AclRule) -> str:
    return f"{rule.principal_type.value}:{rule.principal_id}"


def effective_access_principals(
    organization_id: object,
    visibility: Visibility,
    kb_acl: Iterable[AclRule],
    document_acl: Iterable[AclRule] = (),
) -> list[str]:
    """Principal tokens copied onto a document's chunks (`access_principals`), matched against
    `principal_tokens(ctx)` at query time (materialized by `app.services.chunk_acl`).

    Document ACL (if any) wins because it can only narrow; otherwise the KB's ACL for restricted
    KBs, or the whole organization.
    """
    document_acl = list(document_acl)
    if document_acl:
        return sorted({_token(r) for r in document_acl})
    if visibility is Visibility.RESTRICTED:
        return sorted({_token(r) for r in kb_acl})
    return [f"org:{organization_id}"]
