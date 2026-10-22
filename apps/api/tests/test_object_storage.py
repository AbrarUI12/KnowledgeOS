"""T2.2 ObjectStore provider tests."""

import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
import pytest

from app.core.config import Settings
from app.providers.storage import (
    InMemoryObjectStore,
    ObjectStore,
    ObjectStoreError,
    S3ObjectStore,
    canonical_artifact_key,
    quarantine_original_key,
    trusted_original_key,
)
from tests.support import make_settings


@pytest.mark.unit
def test_key_helpers_use_only_server_generated_ids() -> None:
    org_id, kb_id, upload_id, document_id, version_id = (uuid.uuid4() for _ in range(5))

    assert quarantine_original_key(org_id, kb_id, upload_id) == (
        f"{org_id}/{kb_id}/{upload_id}/original"
    )
    assert trusted_original_key(org_id, kb_id, document_id, version_id) == (
        f"{org_id}/{kb_id}/{document_id}/{version_id}/original"
    )
    assert canonical_artifact_key(org_id, kb_id, document_id, version_id) == (
        f"{org_id}/{kb_id}/{document_id}/{version_id}/canonical.json"
    )


@pytest.mark.unit
async def test_in_memory_store_round_trip_copy_and_idempotent_delete() -> None:
    store = InMemoryObjectStore()
    assert isinstance(store, ObjectStore)

    created = await store.put("source", "path/original", b"abcdef", content_type="text/plain")
    assert created.size_bytes == 6
    assert created.content_type == "text/plain"
    assert await store.exists("source", "path/original")
    assert await store.head("source", "missing") is None
    assert (
        b"".join([part async for part in store.get_stream("source", "path/original", chunk_size=2)])
        == b"abcdef"
    )
    assert await store.get_bytes("source", "path/original", max_bytes=6) == b"abcdef"

    await store.copy("source", "path/original", "trusted", "path/original")
    copied = await store.head("trusted", "path/original")
    assert copied is not None
    assert copied.content_type == "text/plain"
    assert await store.get_bytes("trusted", "path/original", max_bytes=6) == b"abcdef"

    await store.delete("source", "path/original")
    await store.delete("source", "path/original")
    assert not await store.exists("source", "path/original")


@pytest.mark.unit
async def test_in_memory_store_enforces_bounds_and_missing_objects() -> None:
    store = InMemoryObjectStore()
    await store.put("bucket", "key", b"1234", content_type="application/octet-stream")

    with pytest.raises(ObjectStoreError, match="exceeds max_bytes"):
        await store.get_bytes("bucket", "key", max_bytes=3)
    with pytest.raises(ObjectStoreError, match="object not found"):
        await store.get_bytes("bucket", "missing", max_bytes=10)
    with pytest.raises(ObjectStoreError, match="object not found"):
        _ = [part async for part in store.get_stream("bucket", "missing")]
    with pytest.raises(ValueError, match="chunk_size"):
        store.get_stream("bucket", "key", chunk_size=0)


@pytest.mark.unit
async def test_presigns_with_bound_content_type_and_public_endpoint() -> None:
    store = S3ObjectStore(
        endpoint_url="http://minio:9000",
        public_endpoint_url="http://localhost:9000",
        region_name="us-east-1",
        access_key_id="test-key",
        secret_access_key="test-secret",
        force_path_style=True,
    )

    before = datetime.now(UTC)
    upload = await store.presign_put(
        "quarantine",
        "org/kb/upload/original",
        content_type="application/pdf",
        expires_in_seconds=60,
    )

    parsed = urlparse(upload.url)
    assert parsed.netloc == "localhost:9000"
    assert parsed.path == "/quarantine/org/kb/upload/original"
    assert upload.method == "PUT"
    assert upload.headers == {"Content-Type": "application/pdf"}
    assert before < upload.expires_at
    assert "test-secret" not in upload.url


@pytest.mark.integration
async def test_s3_store_minio_presign_put_head_get_copy_delete(
    integration_settings: Settings,
) -> None:
    store = S3ObjectStore.from_settings(integration_settings)
    assert isinstance(store, ObjectStore)
    source_object_path = f"tests/{uuid.uuid4()}/original"
    copied_object_path = f"tests/{uuid.uuid4()}/original"
    artifact_object_path = f"tests/{uuid.uuid4()}/canonical.json"
    data = b"KnowledgeOS object storage integration"
    content_type = "text/plain"

    upload = await store.presign_put(
        integration_settings.s3_bucket_quarantine,
        source_object_path,
        content_type=content_type,
        expires_in_seconds=120,
    )
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.put(upload.url, content=data, headers=upload.headers)
    assert response.status_code in {200, 204}

    try:
        info = await store.head(integration_settings.s3_bucket_quarantine, source_object_path)
        assert info is not None
        assert info.size_bytes == len(data)
        assert info.content_type == content_type
        assert await store.exists(integration_settings.s3_bucket_quarantine, source_object_path)
        assert (
            await store.get_bytes(
                integration_settings.s3_bucket_quarantine,
                source_object_path,
                max_bytes=len(data),
            )
            == data
        )
        assert (
            b"".join(
                [
                    part
                    async for part in store.get_stream(
                        integration_settings.s3_bucket_quarantine,
                        source_object_path,
                        chunk_size=7,
                    )
                ]
            )
            == data
        )
        with pytest.raises(ObjectStoreError, match="exceeds max_bytes"):
            await store.get_bytes(
                integration_settings.s3_bucket_quarantine,
                source_object_path,
                max_bytes=len(data) - 1,
            )

        await store.copy(
            integration_settings.s3_bucket_quarantine,
            source_object_path,
            integration_settings.s3_bucket_trusted,
            copied_object_path,
        )
        assert (
            await store.get_bytes(
                integration_settings.s3_bucket_trusted,
                copied_object_path,
                max_bytes=len(data),
            )
            == data
        )
        # A signed GET (T5.4 source viewer) downloads the bytes inline, under the given name.
        download = await store.presign_get(
            integration_settings.s3_bucket_trusted,
            copied_object_path,
            expires_in_seconds=60,
            filename='Leave "policy".pdf',
        )
        async with httpx.AsyncClient(trust_env=False) as client:
            fetched = await client.get(download.url)
        assert fetched.status_code == 200
        assert fetched.content == data
        assert fetched.headers["content-disposition"] == 'inline; filename="Leave policy.pdf"'
        artifact = await store.put(
            integration_settings.s3_bucket_artifacts,
            artifact_object_path,
            b'{"schema_version":1}',
            content_type="application/json",
        )
        assert artifact.size_bytes == 20
        assert artifact.content_type == "application/json"
        assert await store.head(integration_settings.s3_bucket_quarantine, "missing") is None
    finally:
        await store.delete(integration_settings.s3_bucket_quarantine, source_object_path)
        await store.delete(integration_settings.s3_bucket_trusted, copied_object_path)
        await store.delete(integration_settings.s3_bucket_trusted, copied_object_path)
        await store.delete(integration_settings.s3_bucket_artifacts, artifact_object_path)

    assert not await store.exists(integration_settings.s3_bucket_quarantine, source_object_path)
    assert not await store.exists(integration_settings.s3_bucket_trusted, copied_object_path)


@pytest.mark.unit
def test_s3_clients_use_explicit_timeouts_and_bounded_retries() -> None:
    store = S3ObjectStore.from_settings(
        make_settings(
            s3_connect_timeout_seconds=4.0, s3_read_timeout_seconds=25.0, s3_max_attempts=2
        )
    )
    for client in (store._client, store._presign_client):
        config = client.meta.config  # botocore stubs don't declare these attributes
        assert getattr(config, "connect_timeout", None) == 4.0
        assert getattr(config, "read_timeout", None) == 25.0
        assert getattr(config, "retries", None) == {"total_max_attempts": 2, "mode": "standard"}
