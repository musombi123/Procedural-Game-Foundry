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


def test_toolchain_catalog_reports_manual_tools_and_android_sdk_install(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    client = make_client(tmp_path)
    result = client.get("/api/v1/desktop/toolchains")
    assert result.status_code == 200
    payload = result.json()
    by_id = {item["id"]: item for item in payload["catalog"]}
    assert by_id["android_sdk"]["installable"] is True
    assert by_id["godot4"]["installable"] is False
    assert payload["android_export_ready"] is False
    assert payload["tools"]["godot4"]["available"] is False


def test_toolchain_install_requires_consent_and_fixed_android_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    client = make_client(tmp_path)
    denied = client.post(
        "/api/v1/desktop/toolchains/install",
        json={"tools": ["android_sdk"], "confirm_install": False},
    )
    assert denied.status_code == 403
    unsupported = client.post(
        "/api/v1/desktop/toolchains/install",
        json={"tools": ["godot4"], "confirm_install": True},
    )
    assert unsupported.status_code == 422


def test_godot_build_requires_real_export_preset_and_local_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    client = make_client(tmp_path)
    workspace = tmp_path / "creator-projects"
    client.put("/api/v1/desktop/workspace", json={"path": str(workspace)})
    source = tmp_path / "source-game"
    source.mkdir()
    (source / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (source / "export_presets.cfg").write_text(
        '[preset.0]\nname="Windows Desktop"\nplatform="Windows Desktop"\n',
        encoding="utf-8",
    )
    created = client.post("/api/v1/desktop/projects/import", json={"path": str(source)})
    project_id = created.json()["project"]["id"]

    invalid = client.post(
        f"/api/v1/desktop/projects/{project_id}/build",
        json={"preset": "Made Up Preset", "output_name": "game.exe", "mode": "release"},
    )
    assert invalid.status_code == 422

    valid_but_no_engine = client.post(
        f"/api/v1/desktop/projects/{project_id}/build",
        json={"preset": "Windows Desktop", "output_name": "game.exe", "mode": "release"},
    )
    assert valid_but_no_engine.status_code == 409
