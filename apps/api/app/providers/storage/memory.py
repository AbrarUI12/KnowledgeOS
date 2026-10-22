"""Concurrency-safe in-memory ObjectStore for unit tests and local fakes."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from app.providers.storage.base import (
    ObjectInfo,
    ObjectStoreError,
    PresignedDownload,
    PresignedUpload,
)


@dataclass(frozen=True, slots=True)
class _StoredObject:
    data: bytes
    content_type: str
    etag: str
    last_modified: datetime


class InMemoryObjectStore:
    """An isolated object store whose reads return snapshots of stored bytes."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], _StoredObject] = {}
        self._lock = asyncio.Lock()

    async def presign_put(
        self, bucket: str, key: str, *, content_type: str, expires_in_seconds: int = 900
    ) -> PresignedUpload:
        _validate_location(bucket, key)
        if expires_in_seconds <= 0:
            raise ValueError("expires_in_seconds must be positive")
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
        path = f"{quote(bucket, safe='')}/{quote(key, safe='/')}"
        return PresignedUpload(
            url=f"memory://{path}",
            headers={"Content-Type": content_type},
            expires_at=expires_at,
        )

    async def presign_get(
        self, bucket: str, key: str, *, expires_in_seconds: int = 300, filename: str | None = None
    ) -> PresignedDownload:
        _validate_location(bucket, key)
        if expires_in_seconds <= 0:
            raise ValueError("expires_in_seconds must be positive")
        path = f"{quote(bucket, safe='')}/{quote(key, safe='/')}"
        return PresignedDownload(
            url=f"memory://{path}?get",
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        )

    async def head(self, bucket: str, key: str) -> ObjectInfo | None:
        _validate_location(bucket, key)
        async with self._lock:
            stored = self._objects.get((bucket, key))
        return None if stored is None else _info(bucket, key, stored)

    def get_stream(
        self, bucket: str, key: str, *, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        _validate_location(bucket, key)
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

        async def stream() -> AsyncIterator[bytes]:
            async with self._lock:
                stored = self._objects.get((bucket, key))
            if stored is None:
                raise ObjectStoreError(f"object not found: s3://{bucket}/{key}")
            for offset in range(0, len(stored.data), chunk_size):
                yield stored.data[offset : offset + chunk_size]

        return stream()

    async def get_bytes(self, bucket: str, key: str, *, max_bytes: int) -> bytes:
        _validate_location(bucket, key)
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        async with self._lock:
            stored = self._objects.get((bucket, key))
        if stored is None:
            raise ObjectStoreError(f"object not found: s3://{bucket}/{key}")
        if len(stored.data) > max_bytes:
            raise ObjectStoreError(f"object s3://{bucket}/{key} exceeds max_bytes={max_bytes}")
        return stored.data

    async def put(self, bucket: str, key: str, data: bytes, *, content_type: str) -> ObjectInfo:
        _validate_location(bucket, key)
        stored = _StoredObject(
            data=bytes(data),
            content_type=content_type,
            etag=hashlib.sha256(data).hexdigest(),
            last_modified=datetime.now(UTC),
        )
        async with self._lock:
            self._objects[(bucket, key)] = stored
        return _info(bucket, key, stored)

    async def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        _validate_location(src_bucket, src_key)
        _validate_location(dst_bucket, dst_key)
        async with self._lock:
            source = self._objects.get((src_bucket, src_key))
            if source is None:
                raise ObjectStoreError(f"object not found: s3://{src_bucket}/{src_key}")
            self._objects[(dst_bucket, dst_key)] = _StoredObject(
                data=source.data,
                content_type=source.content_type,
                etag=source.etag,
                last_modified=datetime.now(UTC),
            )

    async def delete(self, bucket: str, key: str) -> None:
        _validate_location(bucket, key)
        async with self._lock:
            self._objects.pop((bucket, key), None)

    async def exists(self, bucket: str, key: str) -> bool:
        return await self.head(bucket, key) is not None


def _validate_location(bucket: str, key: str) -> None:
    if not bucket:
        raise ValueError("bucket must not be empty")
    if not key:
        raise ValueError("key must not be empty")


def _info(bucket: str, key: str, stored: _StoredObject) -> ObjectInfo:
    return ObjectInfo(
        bucket=bucket,
        key=key,
        size_bytes=len(stored.data),
        content_type=stored.content_type,
        etag=stored.etag,
        last_modified=stored.last_modified,
    )
