from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import services.api.main as api
from services.api.auth import current_principal
from services.storage.postgres import database
from services.api import workspace


@pytest.fixture
def owner_client(monkeypatch):
    owner_id = f"test-owner-{uuid4().hex}"
    monkeypatch.setitem(api.app.dependency_overrides, current_principal, lambda: {"id": owner_id, "name": "Test Creator"})
    with TestClient(api.app) as client:
        yield owner_id, client
    with database() as connection:
        connection.execute("DELETE FROM nexora_projects WHERE owner_id=%s", (owner_id,))
    api.app.dependency_overrides.pop(current_principal, None)


def sample_document():
    return {
        "schemaVersion": 1,
        "id": "browser-project-id",
        "engine": "Godot 4",
        "settings": {"target": "Desktop", "orientation": "Landscape"},
        "scene": {
            "id": "main-scene",
            "name": "Main Scene",
            "objects": [{
                "id": "world-root",
                "name": "World",
                "type": "Node3D",
                "position": [0, 0, 0],
                "rotation": [0, 0, 0],
                "scale": [1, 1, 1],
                "visible": True,
            }],
        },
        "assets": [],
        "gameplay": {"enemies": [], "mechanics": [], "objectives": []},
    }


def create_cloud_project(client):
    response = client.post("/api/v1/workspace/projects", json={
        "name": "Cloud Test World",
        "description": "Owner-isolated cloud project",
        "document": sample_document(),
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_project_crud_revision_and_owner_isolation(owner_client):
    owner_id, client = owner_client
    created = create_cloud_project(client)
    project_id = created["id"]
    assert created["version"] == 1
    assert created["document"]["id"] == project_id

    listed = client.get("/api/v1/workspace/projects")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["projects"]] == [project_id]

    changed_document = created["document"]
    changed_document["description"] = "Updated in the cloud"
    updated = client.put(f"/api/v1/workspace/projects/{project_id}", json={
        "name": "Cloud Test World",
        "description": "Second revision",
        "document": changed_document,
        "expected_version": 1,
    })
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["document"]["id"] == project_id

    conflict = client.put(f"/api/v1/workspace/projects/{project_id}", json={
        "name": "Stale update",
        "description": "",
        "document": changed_document,
        "expected_version": 1,
    })
    assert conflict.status_code == 409

    revisions = client.get(f"/api/v1/workspace/projects/{project_id}/revisions")
    assert revisions.status_code == 200
    assert [item["version"] for item in revisions.json()["revisions"]] == [2, 1]

    api.app.dependency_overrides[current_principal] = lambda: {"id": "different-user", "name": ""}
    assert client.get(f"/api/v1/workspace/projects/{project_id}").status_code == 404
    api.app.dependency_overrides[current_principal] = lambda: {"id": owner_id, "name": "Test Creator"}


def test_private_asset_presign_completion_and_download(owner_client, monkeypatch):
    _, client = owner_client
    project = create_cloud_project(client)
    invalid_asset = client.get(f"/api/v1/workspace/projects/{project['id']}/assets/not-a-uuid/download-url")
    assert invalid_asset.status_code == 404
    monkeypatch.setattr(workspace.object_store, "presigned_put", lambda key, content_type, expires=600: "https://r2.invalid/signed-put")
    monkeypatch.setattr(workspace.object_store, "head", lambda key: {"ContentLength": 2048, "ContentType": "model/gltf-binary"})
    monkeypatch.setattr(workspace.object_store, "presigned_get", lambda key, filename, expires=600: "https://r2.invalid/signed-get")

    intent = client.post(f"/api/v1/workspace/projects/{project['id']}/assets/upload-url", json={
        "filename": "creator-model.glb",
        "content_type": "model/gltf-binary",
        "size": 2048,
    })
    assert intent.status_code == 201, intent.text
    assert intent.json()["method"] == "PUT"
    asset_id = intent.json()["asset_id"]

    completed = client.post(f"/api/v1/workspace/projects/{project['id']}/assets/{asset_id}/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "ready"

    download = client.get(f"/api/v1/workspace/projects/{project['id']}/assets/{asset_id}/download-url")
    assert download.status_code == 200
    assert download.json()["download_url"] == "https://r2.invalid/signed-get"


def test_production_jobs_are_persisted_and_owner_scoped(owner_client):
    owner_id, client = owner_client
    project = create_cloud_project(client)
    queued = client.post(f"/api/v1/workspace/projects/{project['id']}/jobs", json={
        "kind": "build.export",
        "target": "android",
    })
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["job_id"]

    jobs = client.get(f"/api/v1/workspace/projects/{project['id']}/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["id"] == job_id

    api.app.dependency_overrides[current_principal] = lambda: {"id": "different-user", "name": ""}
    assert client.get(f"/api/v1/workspace/jobs/{job_id}").status_code == 404
    api.app.dependency_overrides[current_principal] = lambda: {"id": owner_id, "name": "Test Creator"}
