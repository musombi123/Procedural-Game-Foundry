"""Cloud platform readiness checks for the hosted Nexora API.

Liveness is intentionally independent of external services. Readiness verifies the
configured PostgreSQL and S3-compatible object store without exposing credentials.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException


router = APIRouter(tags=["platform"])


def _database_check() -> dict[str, Any]:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return {"status": "not_configured"}
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return {"status": "ok"}
    except Exception:
        return {"status": "unavailable"}


def _object_storage_check() -> dict[str, Any]:
    endpoint = os.getenv("PGF_OBJECT_STORAGE_ENDPOINT", "").strip()
    bucket = os.getenv("PGF_OBJECT_STORAGE_BUCKET", "").strip()
    access_key = os.getenv("PGF_OBJECT_STORAGE_ACCESS_KEY", "").strip()
    secret_key = os.getenv("PGF_OBJECT_STORAGE_SECRET_KEY", "").strip()
    if not all((endpoint, bucket, access_key, secret_key)):
        return {"status": "not_configured"}
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=os.getenv("PGF_OBJECT_STORAGE_REGION", "auto"),
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                connect_timeout=3,
                read_timeout=3,
                retries={"max_attempts": 1},
            ),
        )
        client.head_bucket(Bucket=bucket)
        return {"status": "ok"}
    except Exception:
        return {"status": "unavailable"}


def platform_status() -> dict[str, Any]:
    required = os.getenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "false").lower() == "true"
    database = _database_check()
    object_storage = _object_storage_check()
    configured = database["status"] != "not_configured" and object_storage["status"] != "not_configured"
    checks_ok = database["status"] == "ok" and object_storage["status"] == "ok"
    ready = checks_ok if required else (not configured or checks_ok)
    return {
        "status": "ready" if ready else "not_ready",
        "mode": "cloud" if required else "local_or_cloud",
        "checks": {"database": database, "object_storage": object_storage},
        "required_dependencies_configured": configured,
    }


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive", "service": "nexora-foundry-api"}


@router.get("/health/ready")
def readiness() -> dict[str, Any]:
    result = platform_status()
    if result["status"] != "ready":
        raise HTTPException(status_code=503, detail=result)
    return result
