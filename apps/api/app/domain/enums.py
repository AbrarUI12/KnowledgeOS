"""Shared enumerations used by API schemas, ORM models and workers (T1.0 contract).

Values are stable API strings; the database stores them as text + CHECK constraints (D-012).
"""

from enum import StrEnum


class Visibility(StrEnum):
    ORGANIZATION = "organization"  # every member with query.execute
    RESTRICTED = "restricted"  # only principals on the ACL


class PrincipalType(StrEnum):
    USER = "user"
    GROUP = "group"
    ROLE = "role"


class AclPermission(StrEnum):
    QUERY = "query"
    MANAGE = "manage"


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class DocumentStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ApprovalStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class IngestionState(StrEnum):
    """Ingestion job state machine (plan §14). Terminal: READY, QUARANTINED, FAILED_*, CANCELLED."""

    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    MALWARE_SCAN = "MALWARE_SCAN"
    PARSING = "PARSING"
    NORMALIZING = "NORMALIZING"
    SECURITY_SCAN = "SECURITY_SCAN"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    VERIFYING = "VERIFYING"
    READY = "READY"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    QUARANTINED = "QUARANTINED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    CANCELLED = "CANCELLED"


TERMINAL_INGESTION_STATES = frozenset(
    {
        IngestionState.READY,
        IngestionState.QUARANTINED,
        IngestionState.FAILED_PERMANENT,
        IngestionState.CANCELLED,
    }
)


class MatchType(StrEnum):
    EXACT = "exact"  # lexical branch only
    SEMANTIC = "semantic"  # dense branch only
    BOTH = "both"


class EvidenceStatus(StrEnum):
    """Answer trust signal derived from explicit rules, never model 'confidence' (plan §21.3)."""

    STRONG = "strong"
    PARTIAL = "partial"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"
    SOURCE_UNAVAILABLE = "source_unavailable"
    RETRIEVAL_DEGRADED = "retrieval_degraded"


class FeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"
