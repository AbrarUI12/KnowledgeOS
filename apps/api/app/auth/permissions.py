"""Permission catalogue and default role → permission mapping (plan §7.2).

Authorization checks always use permission strings, never role names. Roles are just named
bundles of permissions; organizations get the five system roles below and may add custom roles.

If you change SYSTEM_ROLE_PERMISSIONS, add a migration that syncs the stored system roles
(tests/test_identity_schema.py fails on drift between this module and the database).
"""

import uuid
from enum import StrEnum


class Permission(StrEnum):
    ORG_MANAGE = "org.manage"
    MEMBERS_MANAGE = "members.manage"
    GROUPS_MANAGE = "groups.manage"
    KB_CREATE = "kb.create"
    KB_MANAGE = "kb.manage"
    DOCUMENT_UPLOAD = "document.upload"
    DOCUMENT_PUBLISH = "document.publish"
    DOCUMENT_DELETE = "document.delete"
    QUERY_EXECUTE = "query.execute"
    RETRIEVAL_DEBUG = "retrieval.debug"
    EVALUATION_MANAGE = "evaluation.manage"
    AUDIT_READ = "audit.read"
    API_KEYS_MANAGE = "api_keys.manage"
    MODEL_POLICY_MANAGE = "model_policy.manage"


class SystemRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    KNOWLEDGE_MANAGER = "knowledge_manager"
    MEMBER = "member"
    VIEWER = "viewer"


P = Permission

SYSTEM_ROLE_PERMISSIONS: dict[SystemRole, frozenset[Permission]] = {
    # Everything, including org settings, identity integration, model/privacy policy.
    SystemRole.OWNER: frozenset(Permission),
    # Runs the workspace day to day; cannot change org-level settings or model/privacy policy.
    SystemRole.ADMIN: frozenset(Permission) - {P.ORG_MANAGE, P.MODEL_POLICY_MANAGE},
    # Curates content: uploads, approves, replaces and retires documents.
    SystemRole.KNOWLEDGE_MANAGER: frozenset(
        {P.DOCUMENT_UPLOAD, P.DOCUMENT_PUBLISH, P.DOCUMENT_DELETE, P.QUERY_EXECUTE}
    ),
    # Employees: search and ask over content they're allowed to see.
    SystemRole.MEMBER: frozenset({P.QUERY_EXECUTE}),
    # Read/query only. (Member gains workspace features such as projects in later sessions.)
    SystemRole.VIEWER: frozenset({P.QUERY_EXECUTE}),
}

SYSTEM_ROLE_NAMES: dict[SystemRole, str] = {
    SystemRole.OWNER: "Owner",
    SystemRole.ADMIN: "Administrator",
    SystemRole.KNOWLEDGE_MANAGER: "Knowledge manager",
    SystemRole.MEMBER: "Member",
    SystemRole.VIEWER: "Viewer",
}


# Deterministic system-role IDs (same UUID in every environment). Migration 0002 contains a
# literal copy of this namespace; tests assert they agree.
SYSTEM_ROLE_NAMESPACE = uuid.UUID("6f1c0a52-3d1e-4c8a-9a51-6b8f3f0d2b11")


def system_role_id(role: SystemRole) -> uuid.UUID:
    return uuid.uuid5(SYSTEM_ROLE_NAMESPACE, f"system-role:{role.value}")
