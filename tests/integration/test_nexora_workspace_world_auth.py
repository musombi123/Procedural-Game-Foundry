from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.nexora_workspace.api import register_nexora_workspace_routes
from core.orchestration.jobs import JobRegistry
from core.project_engine.manager import ProjectManager


def make_client(tmp_path, user_id: str):
    app = FastAPI()

    @app.middleware("http")
    async def attach_test_identity(request: Request, call_next):
        request.state.nexora_user_id = user_id
        request.state.nexora_user = {"id": user_id}
        return await call_next(request)

    manager = ProjectManager(tmp_path / "projects")
    register_nexora_workspace_routes(app, manager, JobRegistry())
    return TestClient(app)


def test_world_document_is_persisted_for_project_owner(tmp_path):
    client = make_client(tmp_path, "creator-one")
    created = client.post(
        "/api/v1/workspace/projects",
        json={
            "name": "World Builder Integration",
            "description": "Owner-scoped WorldDocument test",
            "document": {},
        },
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    world = client.get(f"/api/v1/workspace/projects/{project_id}/world")
    assert world.status_code == 200
    assert world.json()["seed"] >= 0

    payload = {
        "seed": 55,
        "world": {
            "width": 112,
            "depth": 96,
            "resolution": 64,
            "amplitude": 12,
            "frequency": 0.06,
            "biomes": ["rocky-desert", "alien-forest"],
            "weather": True,
        },
        "objects": [{
            "id": "obj-beacon1",
            "name": "Signal beacon",
            "kind": "beacon",
            "x": 8,
            "y": 0,
            "z": -5,
            "rotation": 35,
            "scale": 1.2,
            "color": "#5b8da8",
            "model_asset_id": None,
        }],
        "terrain_edits": [{
            "id": "terrain-edit-1",
            "operation": "raise",
            "x": 4,
            "z": -3,
            "radius": 7,
            "strength": 2.5,
        }],
        "sun_angle": 35,
        "fog": False,
        "water_level": -2,
    }
    saved = client.put(f"/api/v1/workspace/projects/{project_id}/world", json=payload)
    assert saved.status_code == 200
    assert saved.json()["objects"] == 1
    assert saved.json()["seed"] == 55

    restored = client.get(f"/api/v1/workspace/projects/{project_id}/world")
    assert restored.status_code == 200
    assert restored.json()["world"]["width"] == 112
    assert restored.json()["objects"][0]["name"] == "Signal beacon"
    assert restored.json()["terrain_edits"][0]["operation"] == "raise"


def test_world_document_cannot_be_read_or_written_by_another_account(tmp_path):
    owner_client = make_client(tmp_path, "creator-owner")
    created = owner_client.post(
        "/api/v1/workspace/projects",
        json={"name": "Private World", "description": "", "document": {}},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    other_client = make_client(tmp_path, "creator-other")
    assert other_client.get(f"/api/v1/workspace/projects/{project_id}/world").status_code == 404
    assert other_client.put(
        f"/api/v1/workspace/projects/{project_id}/world",
        json={"seed": 1},
    ).status_code == 404
