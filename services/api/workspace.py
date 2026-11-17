"""Authenticated, owner-scoped NEXORA cloud workspace API.

Project documents and revisions live in PostgreSQL. Binary assets remain in a
private S3-compatible bucket and are only transferred through short-lived,
owner-authorized pre-signed URLs. No browser-supplied owner ID is trusted.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb

from services.api.auth import current_principal
from services.storage.postgres import database, ensure_schema
from services.storage import object_store


router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_ASSET_BYTES = 100 * 1024 * 1024
ALLOWED_ASSET_TYPES = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
}


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    document: dict[str, Any]


class ProjectUpdateRequest(ProjectCreateRequest):
    expected_version: int = Field(ge=1)


class UploadIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=160)
    size: int = Field(gt=0, le=MAX_ASSET_BYTES)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(scene.generate|build.export)$")
    target: str = Field(default="desktop", pattern=r"^(desktop|android|desktop_android)$")


def _json_document(document: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(document, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Project document must contain finite JSON values.") from exc
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Project documents are limited to 5 MB.")
    scene = document.get("scene") if isinstance(document, dict) else None
    objects = scene.get("objects", []) if isinstance(scene, dict) else []
    if not isinstance(objects, list) or len(objects) > 500:
        raise HTTPException(status_code=422, detail="Scene objects must be a list containing at most 500 nodes.")
    for index, item in enumerate(objects):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise HTTPException(status_code=422, detail=f"Scene node {index + 1} requires a name.")
        for field in ("position", "rotation", "scale"):
            vector = item.get(field)
            if not isinstance(vector, list) or len(vector) != 3:
                raise HTTPException(status_code=422, detail=f"Scene node {index + 1} has an invalid {field} vector.")
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not (-100000 <= value <= 100000):
                    raise HTTPException(status_code=422, detail=f"Scene node {index + 1} has an invalid {field} value.")
    return document


def _safe_filename(value: str) -> str:
    name = value.replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=422, detail="A valid asset filename is required.")
    return name[:180]


def _asset_uuid(asset_id: str) -> UUID:
    try:
        return UUID(asset_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Asset not found.") from exc


def _owned_project(connection, project_id: str, owner_id: str):
    try:
        pid = UUID(project_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    row = connection.execute(
        "SELECT id, owner_id, name, description, document, version, created_at, updated_at "
        "FROM nexora_projects WHERE id = %s AND owner_id = %s",
        (pid, owner_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    return row


def _project_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "document": row["document"],
        "version": row["version"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def _db():
    context = None
    try:
        context = database()
        connection = context.__enter__()
        ensure_schema(connection)
        return context, connection
    except Exception as exc:
        if context is not None:
            context.__exit__(*sys.exc_info())
        raise HTTPException(status_code=503, detail="NEXORA PostgreSQL is unavailable.") from exc


@router.get("/projects")
def list_projects(principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        rows = connection.execute(
            "SELECT id, owner_id, name, description, document, version, created_at, updated_at "
            "FROM nexora_projects WHERE owner_id = %s ORDER BY updated_at DESC LIMIT 200",
            (principal["id"],),
        ).fetchall()
        return {"projects": [_project_result(row) for row in rows]}
    finally:
        context.__exit__(*sys.exc_info())


@router.post("/projects", status_code=201)
def create_project(request: ProjectCreateRequest, principal: dict[str, str] = Depends(current_principal)):
    document = _json_document(request.document)
    project_id = uuid4()
    document = {**document, "id": str(project_id)}
    context, connection = _db()
    try:
        row = connection.execute(
            "INSERT INTO nexora_projects (id, owner_id, name, description, document, version) "
            "VALUES (%s, %s, %s, %s, %s, 1) "
            "RETURNING id, owner_id, name, description, document, version, created_at, updated_at",
            (project_id, principal["id"], request.name.strip(), request.description, Jsonb(document)),
        ).fetchone()
        connection.execute(
            "INSERT INTO nexora_project_revisions (project_id, owner_id, version, snapshot) VALUES (%s, %s, 1, %s)",
            (project_id, principal["id"], Jsonb({"name": request.name.strip(), "description": request.description, "document": document})),
        )
        return _project_result(row)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail="Could not persist the NEXORA project.") from exc
    finally:
        context.__exit__(*sys.exc_info())


@router.get("/projects/{project_id}")
def get_project(project_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        return _project_result(_owned_project(connection, project_id, principal["id"]))
    finally:
        context.__exit__(*sys.exc_info())


@router.put("/projects/{project_id}")
def update_project(project_id: str, request: ProjectUpdateRequest, principal: dict[str, str] = Depends(current_principal)):
    document = _json_document(request.document)
    context, connection = _db()
    try:
        current = _owned_project(connection, project_id, principal["id"])
        document = {**document, "id": str(current["id"])}
        row = connection.execute(
            "UPDATE nexora_projects SET name=%s, description=%s, document=%s, version=version+1, updated_at=now() "
            "WHERE id=%s AND owner_id=%s AND version=%s "
            "RETURNING id, owner_id, name, description, document, version, created_at, updated_at",
            (request.name.strip(), request.description, Jsonb(document), current["id"], principal["id"], request.expected_version),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=409, detail={"code": "version_conflict", "message": "This project changed elsewhere. Reload it before saving.", "current_version": current["version"]})
        connection.execute(
            "INSERT INTO nexora_project_revisions (project_id, owner_id, version, snapshot) VALUES (%s, %s, %s, %s)",
            (current["id"], principal["id"], row["version"], Jsonb({"name": request.name.strip(), "description": request.description, "document": document})),
        )
        return _project_result(row)
    finally:
        context.__exit__(*sys.exc_info())


@router.get("/projects/{project_id}/revisions")
def list_revisions(project_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        rows = connection.execute(
            "SELECT version, snapshot, created_at FROM nexora_project_revisions "
            "WHERE project_id=%s AND owner_id=%s ORDER BY version DESC LIMIT 50",
            (project["id"], principal["id"]),
        ).fetchall()
        return {"current_version": project["version"], "revisions": [
            {"version": row["version"], "snapshot": row["snapshot"], "created_at": row["created_at"].isoformat()}
            for row in rows
        ]}
    finally:
        context.__exit__(*sys.exc_info())


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        active_job = connection.execute(
            "SELECT id FROM nexora_jobs WHERE project_id=%s AND owner_id=%s AND state IN ('queued','running') LIMIT 1",
            (project["id"], principal["id"]),
        ).fetchone()
        if active_job:
            raise HTTPException(status_code=409, detail="Cancel or wait for active production jobs before deleting this project.")
        assets = connection.execute(
            "SELECT object_key, processed_object_key FROM nexora_assets WHERE project_id=%s AND owner_id=%s",
            (project["id"], principal["id"]),
        ).fetchall()
        for asset in assets:
            for key in (asset["object_key"], asset["processed_object_key"]):
                if key:
                    try:
                        object_store.delete(key)
                    except Exception as exc:
                        raise HTTPException(status_code=503, detail="Private asset cleanup failed; project was not deleted.") from exc
        connection.execute("DELETE FROM nexora_projects WHERE id=%s AND owner_id=%s", (project["id"], principal["id"]))
        return None
    finally:
        context.__exit__(*sys.exc_info())


@router.post("/projects/{project_id}/assets/upload-url", status_code=201)
def create_asset_upload(project_id: str, request: UploadIntent, principal: dict[str, str] = Depends(current_principal)):
    filename = _safe_filename(request.filename)
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    expected_type = ALLOWED_ASSET_TYPES.get(extension)
    if not expected_type or request.content_type.split(";", 1)[0].strip().lower() != expected_type:
        raise HTTPException(status_code=415, detail="Unsupported file type or mismatched content type.")
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        asset_id = uuid4()
        owner_namespace = hashlib.sha256(principal["id"].encode("utf-8")).hexdigest()[:32]
        key = f"owners/{owner_namespace}/projects/{project['id']}/assets/{asset_id}/{filename}"
        connection.execute(
            "INSERT INTO nexora_assets (id, project_id, owner_id, object_key, filename, content_type, expected_size, sha256) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (asset_id, project["id"], principal["id"], key, filename, expected_type, request.size, request.sha256.lower() if request.sha256 else None),
        )
        try:
            url = object_store.presigned_put(key, expected_type)
        except Exception as exc:
            connection.execute("DELETE FROM nexora_assets WHERE id=%s AND owner_id=%s", (asset_id, principal["id"]))
            raise HTTPException(status_code=503, detail="Private object storage is unavailable.") from exc
        return {"asset_id": str(asset_id), "upload_url": url, "method": "PUT", "headers": {"Content-Type": expected_type}, "expires_in": 600}
    finally:
        context.__exit__(*sys.exc_info())


@router.post("/projects/{project_id}/assets/{asset_id}/complete")
def complete_asset_upload(project_id: str, asset_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        asset = connection.execute(
            "SELECT * FROM nexora_assets WHERE id=%s AND project_id=%s AND owner_id=%s",
            (UUID(asset_id), project["id"], principal["id"]),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found.")
        if asset["status"] in {"ready", "processed"}:
            return {"asset_id": str(asset["id"]), "status": asset["status"], "size": asset["size"]}
        try:
            metadata = object_store.head(asset["object_key"])
        except Exception as exc:
            raise HTTPException(status_code=409, detail="The uploaded object is not available yet.") from exc
        actual_size = int(metadata.get("ContentLength") or 0)
        actual_type = str(metadata.get("ContentType") or "").split(";", 1)[0].lower()
        if actual_size != asset["expected_size"] or actual_size > MAX_ASSET_BYTES:
            object_store.delete(asset["object_key"])
            connection.execute("DELETE FROM nexora_assets WHERE id=%s", (asset["id"],))
            raise HTTPException(status_code=413, detail="Uploaded asset size did not match its upload intent.")
        if actual_type != asset["content_type"]:
            object_store.delete(asset["object_key"])
            connection.execute("DELETE FROM nexora_assets WHERE id=%s", (asset["id"],))
            raise HTTPException(status_code=415, detail="Uploaded asset content type did not match its upload intent.")
        row = connection.execute(
            "UPDATE nexora_assets SET status='ready', size=%s WHERE id=%s RETURNING id, filename, content_type, size, status, created_at",
            (actual_size, asset["id"]),
        ).fetchone()
        return {"asset_id": str(row["id"]), "filename": row["filename"], "content_type": row["content_type"], "size": row["size"], "status": row["status"]}
    finally:
        context.__exit__(*sys.exc_info())


@router.get("/projects/{project_id}/assets")
def list_assets(project_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        rows = connection.execute(
            "SELECT id, filename, content_type, size, status, created_at FROM nexora_assets "
            "WHERE project_id=%s AND owner_id=%s ORDER BY created_at DESC",
            (project["id"], principal["id"]),
        ).fetchall()
        return {"assets": [
            {"id": str(row["id"]), "filename": row["filename"], "content_type": row["content_type"], "size": row["size"] or 0, "status": row["status"], "created_at": row["created_at"].isoformat()}
            for row in rows
        ]}
    finally:
        context.__exit__(*sys.exc_info())


@router.get("/projects/{project_id}/assets/{asset_id}/download-url")
def asset_download_url(project_id: str, asset_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        asset = connection.execute(
            "SELECT * FROM nexora_assets WHERE id=%s AND project_id=%s AND owner_id=%s",
            (UUID(asset_id), project["id"], principal["id"]),
        ).fetchone()
        if not asset or asset["status"] not in {"ready", "processed"}:
            raise HTTPException(status_code=404, detail="Asset not found.")
        key = asset["processed_object_key"] if asset["status"] == "processed" and asset["processed_object_key"] else asset["object_key"]
        try:
            url = object_store.presigned_get(key, asset["filename"])
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Private object storage is unavailable.") from exc
        return {"download_url": url, "expires_in": 600, "filename": asset["filename"]}
    finally:
        context.__exit__(*sys.exc_info())


@router.delete("/projects/{project_id}/assets/{asset_id}", status_code=204)
def delete_asset(project_id: str, asset_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        asset = connection.execute(
            "SELECT * FROM nexora_assets WHERE id=%s AND project_id=%s AND owner_id=%s",
            (UUID(asset_id), project["id"], principal["id"]),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found.")
        for key in (asset["object_key"], asset["processed_object_key"]):
            if key:
                try:
                    object_store.delete(key)
                except Exception as exc:
                    raise HTTPException(status_code=503, detail="Could not safely remove the private asset object.") from exc
        connection.execute("DELETE FROM nexora_assets WHERE id=%s", (asset["id"],))
        return None
    finally:
        context.__exit__(*sys.exc_info())


@router.post("/projects/{project_id}/assets/{asset_id}/process", status_code=202)
def process_asset(project_id: str, asset_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        asset = connection.execute(
            "SELECT * FROM nexora_assets WHERE id=%s AND project_id=%s AND owner_id=%s AND status IN ('ready','processed')",
            (UUID(asset_id), project["id"], principal["id"]),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Ready asset not found.")
        if asset["filename"].lower().endswith(".glb") is False:
            raise HTTPException(status_code=415, detail="The Blender normalization worker currently accepts self-contained .glb assets.")
        job_id = uuid4()
        payload = {"asset_id": str(asset["id"]), "object_key": asset["object_key"], "filename": asset["filename"]}
        connection.execute(
            "INSERT INTO nexora_jobs (id, project_id, owner_id, kind, payload) VALUES (%s,%s,%s,'asset.process',%s)",
            (job_id, project["id"], principal["id"], Jsonb(payload)),
        )
        connection.execute("UPDATE nexora_assets SET status='processing' WHERE id=%s", (asset["id"],))
        return {"job_id": str(job_id), "state": "queued", "message": "Queued for Blender asset inspection and normalization."}
    finally:
        context.__exit__(*sys.exc_info())


@router.post("/projects/{project_id}/jobs", status_code=202)
def create_production_job(project_id: str, request: JobCreateRequest, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        job_id = uuid4()
        asset_rows = connection.execute(
            "SELECT id, filename, object_key, processed_object_key, status "
            "FROM nexora_assets WHERE project_id=%s AND owner_id=%s "
            "AND status IN ('ready','processed') AND lower(right(filename, 4)) = '.glb'",
            (project["id"], principal["id"]),
        ).fetchall()
        payload = {
            "target": request.target,
            "project": {
                "name": project["name"],
                "description": project["description"],
                "document": project["document"],
                "version": project["version"],
            },
            "assets": [
                {
                    "id": str(asset["id"]),
                    "filename": asset["filename"],
                    "object_key": asset["processed_object_key"] or asset["object_key"],
                    "status": asset["status"],
                }
                for asset in asset_rows
            ],
        }
        connection.execute(
            "INSERT INTO nexora_jobs (id, project_id, owner_id, kind, payload) VALUES (%s,%s,%s,%s,%s)",
            (job_id, project["id"], principal["id"], request.kind, Jsonb(payload)),
        )
        return {"job_id": str(job_id), "state": "queued", "kind": request.kind, "message": "Production job queued for a registered NEXORA build worker."}
    finally:
        context.__exit__(*sys.exc_info())


@router.get("/projects/{project_id}/jobs")
def list_project_jobs(project_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        project = _owned_project(connection, project_id, principal["id"])
        rows = connection.execute(
            "SELECT id, kind, state, progress, message, result, error, created_at, updated_at "
            "FROM nexora_jobs WHERE project_id=%s AND owner_id=%s ORDER BY created_at DESC LIMIT 50",
            (project["id"], principal["id"]),
        ).fetchall()
        return {"jobs": [
            {"id": str(row["id"]), "kind": row["kind"], "state": row["state"], "progress": row["progress"], "message": row["message"], "result": row["result"], "error": row["error"], "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()}
            for row in rows
        ]}
    finally:
        context.__exit__(*sys.exc_info())


@router.get("/jobs/{job_id}")
def get_production_job(job_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        try:
            jid = UUID(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc
        row = connection.execute(
            "SELECT id, project_id, kind, state, progress, message, result, error, created_at, updated_at "
            "FROM nexora_jobs WHERE id=%s AND owner_id=%s",
            (jid, principal["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found.")
        return {"id": str(row["id"]), "project_id": str(row["project_id"]), "kind": row["kind"], "state": row["state"], "progress": row["progress"], "message": row["message"], "result": row["result"], "error": row["error"], "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()}
    finally:
        context.__exit__(*sys.exc_info())



@router.get("/jobs/{job_id}/artifacts")
def list_job_artifacts(job_id: str, principal: dict[str, str] = Depends(current_principal)):
    context, connection = _db()
    try:
        try:
            jid = UUID(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc
        job = connection.execute(
            "SELECT id FROM nexora_jobs WHERE id=%s AND owner_id=%s",
            (jid, principal["id"]),
        ).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        rows = connection.execute(
            "SELECT id, object_key, filename, content_type, size, created_at "
            "FROM nexora_artifacts WHERE job_id=%s AND owner_id=%s ORDER BY created_at",
            (jid, principal["id"]),
        ).fetchall()
        artifacts = []
        for row in rows:
            try:
                url = object_store.presigned_get(row["object_key"], row["filename"], expires=900)
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Private artifact storage is unavailable.") from exc
            artifacts.append({
                "id": str(row["id"]),
                "filename": row["filename"],
                "content_type": row["content_type"],
                "size": row["size"],
                "download_url": url,
                "expires_in": 900,
                "created_at": row["created_at"].isoformat(),
            })
        return {"artifacts": artifacts}
    finally:
        context.__exit__(*sys.exc_info())
