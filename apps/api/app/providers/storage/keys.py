"""Object-key helpers.

Only server-generated UUIDs are accepted. User filenames are metadata and must never become part
of an object key.
"""

import uuid


def quarantine_original_key(
    organization_id: uuid.UUID, knowledge_base_id: uuid.UUID, upload_id: uuid.UUID
) -> str:
    return f"{organization_id}/{knowledge_base_id}/{upload_id}/original"


def trusted_original_key(
    organization_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
) -> str:
    return f"{organization_id}/{knowledge_base_id}/{document_id}/{version_id}/original"


def canonical_artifact_key(
    organization_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
) -> str:
    return f"{organization_id}/{knowledge_base_id}/{document_id}/{version_id}/canonical.json"
