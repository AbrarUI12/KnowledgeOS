"""S3-compatible ObjectStore for AWS S3, MinIO, Backblaze B2 and Cloudflare R2."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.providers.storage.base import (
    ObjectInfo,
    ObjectStoreError,
    PresignedDownload,
    PresignedUpload,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import (
        GetObjectOutputTypeDef,
        HeadObjectOutputTypeDef,
        PutObjectOutputTypeDef,
    )
else:
    S3Client = Any
    GetObjectOutputTypeDef = dict[str, Any]
    HeadObjectOutputTypeDef = dict[str, Any]
    PutObjectOutputTypeDef = dict[str, Any]

_NOT_FOUND_CODES = frozenset({"404", "NoSuchBucket", "NoSuchKey", "NotFound"})
_MAX_PRESIGN_SECONDS = 7 * 24 * 60 * 60


class S3ObjectStore:
    """Async facade over boto3.

    Server operations use the internal endpoint. Presigning uses a second client configured with
    the browser-reachable public endpoint so MinIO URLs never expose a Docker-only hostname.
    Blocking network calls and streaming reads run in worker threads.
    """

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        public_endpoint_url: str | None,
        region_name: str,
        access_key_id: str,
        secret_access_key: str,
        force_path_style: bool = False,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 30.0,
        max_attempts: int = 3,
    ) -> None:
        # Explicit timeouts and bounded standard-mode retries (plan §34.1): a hung storage call
        # must never hold an API request or ingestion stage for minutes.
        config = BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path" if force_path_style else "auto"},
            connect_timeout=connect_timeout_seconds,
            read_timeout=read_timeout_seconds,
            retries={"total_max_attempts": max_attempts, "mode": "standard"},
        )
        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
            config=config,
        )
        self._presign_client: S3Client = boto3.client(
            "s3",
            endpoint_url=public_endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
            config=config,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3ObjectStore":
        return cls(
            endpoint_url=settings.s3_endpoint_url,
            public_endpoint_url=settings.s3_public_endpoint_url,
            region_name=settings.s3_region,
            access_key_id=settings.s3_access_key_id.get_secret_value(),
            secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            force_path_style=settings.s3_force_path_style,
            connect_timeout_seconds=settings.s3_connect_timeout_seconds,
            read_timeout_seconds=settings.s3_read_timeout_seconds,
            max_attempts=settings.s3_max_attempts,
        )

    async def presign_put(
        self, bucket: str, key: str, *, content_type: str, expires_in_seconds: int = 900
    ) -> PresignedUpload:
        # S3 presigned PUTs can't bind Content-Length; upload completion HEAD-verifies the size.
        _validate_location(bucket, key)
        if not 1 <= expires_in_seconds <= _MAX_PRESIGN_SECONDS:
            raise ValueError("expires_in_seconds must be between 1 and 604800")
        try:
            url = self._presign_client.generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires_in_seconds,
                HttpMethod="PUT",
            )
        except (BotoCoreError, ClientError, ValueError) as exc:
            raise _error("presign PUT", bucket, key, exc) from exc
        return PresignedUpload(
            url=url,
            headers={"Content-Type": content_type},
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        )

    async def presign_get(
        self, bucket: str, key: str, *, expires_in_seconds: int = 300, filename: str | None = None
    ) -> PresignedDownload:
        _validate_location(bucket, key)
        if not 1 <= expires_in_seconds <= _MAX_PRESIGN_SECONDS:
            raise ValueError("expires_in_seconds must be between 1 and 604800")
        params: dict[str, str] = {"Bucket": bucket, "Key": key}
        if filename:
            safe = "".join(c for c in filename if c.isprintable() and c not in '"\\')[:200]
            params["ResponseContentDisposition"] = f'inline; filename="{safe}"'
        try:
            url = self._presign_client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=expires_in_seconds, HttpMethod="GET"
            )
        except (BotoCoreError, ClientError, ValueError) as exc:
            raise _error("presign GET", bucket, key, exc) from exc
        return PresignedDownload(
            url=url, expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
        )

    async def head(self, bucket: str, key: str) -> ObjectInfo | None:
        _validate_location(bucket, key)
        try:
            response: HeadObjectOutputTypeDef = await asyncio.to_thread(
                self._client.head_object, Bucket=bucket, Key=key
            )
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise _error("HEAD", bucket, key, exc) from exc
        except BotoCoreError as exc:
            raise _error("HEAD", bucket, key, exc) from exc
        return _object_info(bucket, key, response)

    def get_stream(
        self, bucket: str, key: str, *, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        _validate_location(bucket, key)
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

        async def stream() -> AsyncIterator[bytes]:
            try:
                response: GetObjectOutputTypeDef = await asyncio.to_thread(
                    self._client.get_object, Bucket=bucket, Key=key
                )
                body = response["Body"]
                try:
                    while chunk := await asyncio.to_thread(body.read, chunk_size):
                        yield chunk
                finally:
                    body.close()
            except (BotoCoreError, ClientError, OSError) as exc:
                raise _error("GET", bucket, key, exc) from exc

        return stream()

    async def get_bytes(self, bucket: str, key: str, *, max_bytes: int) -> bytes:
        _validate_location(bucket, key)
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        try:
            response: GetObjectOutputTypeDef = await asyncio.to_thread(
                self._client.get_object, Bucket=bucket, Key=key
            )
            body = response["Body"]
            try:
                content_length = int(response.get("ContentLength", 0))
                if content_length > max_bytes:
                    raise ObjectStoreError(
                        f"object s3://{bucket}/{key} exceeds max_bytes={max_bytes}"
                    )
                data = await asyncio.to_thread(body.read, max_bytes + 1)
            finally:
                body.close()
        except ObjectStoreError:
            raise
        except (BotoCoreError, ClientError, OSError) as exc:
            raise _error("GET", bucket, key, exc) from exc
        if len(data) > max_bytes:
            raise ObjectStoreError(f"object s3://{bucket}/{key} exceeds max_bytes={max_bytes}")
        return data

    async def put(self, bucket: str, key: str, data: bytes, *, content_type: str) -> ObjectInfo:
        _validate_location(bucket, key)
        try:
            response: PutObjectOutputTypeDef = await asyncio.to_thread(
                self._client.put_object,
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise _error("PUT", bucket, key, exc) from exc
        return ObjectInfo(
            bucket=bucket,
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            etag=_etag(response.get("ETag")),
        )

    async def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        _validate_location(src_bucket, src_key)
        _validate_location(dst_bucket, dst_key)
        try:
            await asyncio.to_thread(
                self._client.copy_object,
                Bucket=dst_bucket,
                Key=dst_key,
                CopySource={"Bucket": src_bucket, "Key": src_key},
            )
        except (BotoCoreError, ClientError) as exc:
            raise _error("COPY", dst_bucket, dst_key, exc) from exc

    async def delete(self, bucket: str, key: str) -> None:
        _validate_location(bucket, key)
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise _error("DELETE", bucket, key, exc) from exc

    async def exists(self, bucket: str, key: str) -> bool:
        return await self.head(bucket, key) is not None


def _object_info(bucket: str, key: str, response: Mapping[str, Any]) -> ObjectInfo:
    return ObjectInfo(
        bucket=bucket,
        key=key,
        size_bytes=int(response["ContentLength"]),
        content_type=response.get("ContentType"),
        etag=_etag(response.get("ETag")),
        last_modified=response.get("LastModified"),
    )


def _etag(value: object) -> str | None:
    return value.strip('"') if isinstance(value, str) else None


def _is_not_found(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in _NOT_FOUND_CODES or status == 404


def _error(action: str, bucket: str, key: str, exc: Exception) -> ObjectStoreError:
    # Deliberately omit endpoints, request details and exception text: provider exceptions can
    # include signed URLs or credential-bearing configuration.
    return ObjectStoreError(f"S3 {action} failed for s3://{bucket}/{key} ({type(exc).__name__})")


def _validate_location(bucket: str, key: str) -> None:
    if not bucket:
        raise ValueError("bucket must not be empty")
    if not key:
        raise ValueError("key must not be empty")
