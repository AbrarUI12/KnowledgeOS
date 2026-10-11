"""Low-level S3 client construction (MinIO locally; Backblaze B2 / R2 when deployed).

The full `ObjectStore` provider interface arrives in Session 13; this module only builds clients.
"""

from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config

from app.core.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client
else:
    S3Client = Any

__all__ = ["S3Client", "create_s3_client"]


def create_s3_client(settings: Settings, *, public: bool = False) -> "S3Client":
    """Build a boto3 S3 client. `public=True` uses the browser-reachable endpoint (presigning)."""
    endpoint = settings.s3_public_endpoint_url if public else settings.s3_endpoint_url
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        config=Config(
            s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
            connect_timeout=2,
            read_timeout=5,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
