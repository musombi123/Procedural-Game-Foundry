"""Private S3-compatible storage helpers (Neon Object Storage and Cloudflare R2)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _setting(primary: str, fallback: str = "") -> str:
    return os.getenv(primary, "").strip() or (os.getenv(fallback, "").strip() if fallback else "")


def configured() -> bool:
    return all((
        _setting("PGF_OBJECT_STORAGE_ENDPOINT", "AWS_ENDPOINT_URL_S3"),
        _setting("PGF_OBJECT_STORAGE_BUCKET", "NEXORA_OBJECT_STORAGE_BUCKET"),
        _setting("PGF_OBJECT_STORAGE_ACCESS_KEY", "AWS_ACCESS_KEY_ID"),
        _setting("PGF_OBJECT_STORAGE_SECRET_KEY", "AWS_SECRET_ACCESS_KEY"),
    ))


def client():
    if not configured():
        raise RuntimeError("NEXORA private object storage is not configured.")
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_setting("PGF_OBJECT_STORAGE_ENDPOINT", "AWS_ENDPOINT_URL_S3"),
        region_name=_setting("PGF_OBJECT_STORAGE_REGION", "AWS_REGION") or "auto",
        aws_access_key_id=_setting("PGF_OBJECT_STORAGE_ACCESS_KEY", "AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_setting("PGF_OBJECT_STORAGE_SECRET_KEY", "AWS_SECRET_ACCESS_KEY"),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=60,
            retries={"max_attempts": 2},
        ),
    )


def bucket() -> str:
    value = _setting("PGF_OBJECT_STORAGE_BUCKET", "NEXORA_OBJECT_STORAGE_BUCKET")
    if not value:
        raise RuntimeError("PGF_OBJECT_STORAGE_BUCKET (or NEXORA_OBJECT_STORAGE_BUCKET) is not configured.")
    return value


def presigned_put(key: str, content_type: str, expires: int = 600) -> str:
    return client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket(), "Key": key, "ContentType": content_type},
        ExpiresIn=max(60, min(int(expires), 900)),
    )


def presigned_get(key: str, filename: str, expires: int = 600) -> str:
    return client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket(),
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename.replace(chr(34), "")}"',
        },
        ExpiresIn=max(60, min(int(expires), 3600)),
    )


def head(key: str) -> dict[str, Any]:
    return client().head_object(Bucket=bucket(), Key=key)


def delete(key: str) -> None:
    client().delete_object(Bucket=bucket(), Key=key)


def upload_file(path: Path, key: str, content_type: str) -> None:
    client().upload_file(str(path), bucket(), key, ExtraArgs={"ContentType": content_type})


def download_file(key: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    client().download_file(bucket(), key, str(path))
