"""Small psycopg persistence layer for the hosted NEXORA workspace."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nexora_projects (
    id UUID PRIMARY KEY,
    owner_id VARCHAR(128) NOT NULL,
    name VARCHAR(80) NOT NULL,
    description VARCHAR(2000) NOT NULL DEFAULT '',
    document JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS nexora_projects_owner_updated
    ON nexora_projects (owner_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS nexora_project_revisions (
    id BIGSERIAL PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES nexora_projects(id) ON DELETE CASCADE,
    owner_id VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL,
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(project_id, version)
);

CREATE TABLE IF NOT EXISTS nexora_assets (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES nexora_projects(id) ON DELETE CASCADE,
    owner_id VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    processed_object_key TEXT,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(160) NOT NULL,
    expected_size BIGINT NOT NULL CHECK (expected_size > 0),
    size BIGINT,
    sha256 CHAR(64),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready','processing','processed','failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS nexora_assets_project_owner
    ON nexora_assets (project_id, owner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS nexora_jobs (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES nexora_projects(id) ON DELETE CASCADE,
    owner_id VARCHAR(128) NOT NULL,
    kind VARCHAR(32) NOT NULL CHECK (kind IN ('asset.process','scene.generate','build.export')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    state VARCHAR(20) NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','completed','failed','cancelled')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    message VARCHAR(500) NOT NULL DEFAULT 'Queued',
    result JSONB,
    error TEXT,
    worker_id VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS nexora_jobs_queue
    ON nexora_jobs (state, created_at) WHERE state IN ('queued','running');
CREATE INDEX IF NOT EXISTS nexora_jobs_owner
    ON nexora_jobs (owner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS nexora_artifacts (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES nexora_jobs(id) ON DELETE CASCADE,
    owner_id VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(160) NOT NULL,
    size BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not configured.")
    return value


@contextmanager
def database() -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url(), connect_timeout=5, row_factory=dict_row) as connection:
        yield connection


def ensure_schema(connection: psycopg.Connection) -> None:
    connection.execute(SCHEMA_SQL)
