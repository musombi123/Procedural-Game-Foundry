from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.worker.desktop_factory import register_desktop_factory_routes


def make_client(tmp_path):
    app = FastAPI()
    register_desktop_factory_routes(app, lambda: "creator-1", tmp_path / "agent")
    return TestClient(app)


def test_local_workspace_import_edit_snapshot_and_restore(tmp_path):
    client = make_client(tmp_path)
    workspace = tmp_path / "creator-projects"
    response = client.put("/api/v1/desktop/workspace", json={"path": str(workspace)})
    assert response.status_code == 200
    assert response.json()["saved"] is True

    source = tmp_path / "source-game"
    source.mkdir()
    (source / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (source / "main.gd").write_text("extends Node\n\nvar value = 1\n", encoding="utf-8")

    imported = client.post(
        "/api/v1/desktop/projects/import",
        json={"path": str(source), "name": "Ownership Test"},
    )
    assert imported.status_code == 200
    project = imported.json()["project"]
    project_id = project["id"]
    assert (workspace / project_id / ".nexora" / "project.json").is_file()
    assert (source / "main.gd").read_text(encoding="utf-8").endswith("1\n")

    initialized = client.post(f"/api/v1/desktop/projects/{project_id}/initialize", json={})
    assert initialized.status_code == 200

    opened = client.get(
        f"/api/v1/desktop/projects/{project_id}/file",
        params={"path": "main.gd"},
    )
    assert opened.status_code == 200
    saved = client.put(
        f"/api/v1/desktop/projects/{project_id}/file",
        json={
            "path": "main.gd",
            "content": "extends Node\n\nvar value = 2\n",
            "expected_sha256": opened.json()["sha256"],
        },
    )
    assert saved.status_code == 200

    snapshot = client.post(f"/api/v1/desktop/projects/{project_id}/snapshots", json={})
    assert snapshot.status_code == 200
    snapshot_id = snapshot.json()["id"]

    changed = client.get(
        f"/api/v1/desktop/projects/{project_id}/file",
        params={"path": "main.gd"},
    )
    assert changed.json()["content"].endswith("2\n")

    restored = client.post(
        f"/api/v1/desktop/projects/{project_id}/snapshots/{snapshot_id}/restore",
        json={},
    )
    assert restored.status_code == 200
    after_restore = client.get(
        f"/api/v1/desktop/projects/{project_id}/file",
        params={"path": "main.gd"},
    )
    assert after_restore.json()["content"].endswith("2\n")


def test_desktop_project_routes_reject_cross_owner_and_path_traversal(tmp_path):
    client = make_client(tmp_path)
    workspace = tmp_path / "creator-projects"
    client.put("/api/v1/desktop/workspace", json={"path": str(workspace)})
    source = tmp_path / "source-game"
    source.mkdir()
    (source / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    created = client.post("/api/v1/desktop/projects/import", json={"path": str(source)})
    project_id = created.json()["project"]["id"]

    traversal = client.get(
        f"/api/v1/desktop/projects/{project_id}/file",
        params={"path": "../../outside.txt"},
    )
    assert traversal.status_code == 422

    release_without_rights = client.post(
        f"/api/v1/desktop/projects/{project_id}/publish/prepare",
        json={"platform": "web", "artifact_id": "missing.zip"},
    )
    assert release_without_rights.status_code == 403


def test_local_desktop_factory_is_not_a_cloud_generation_api(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/v1/desktop/status")
    assert response.status_code == 200
    assert response.json()["agent"]["execution_location"] == "creator_device"
