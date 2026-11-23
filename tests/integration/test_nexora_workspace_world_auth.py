from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.nexora_workspace.api import register_nexora_workspace_routes
from core.orchestration.jobs import Job, JobRegistry, JobState
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
    assert saved.json()["saved"] is True
    assert saved.json()["save_result"]["revision"] >= 1
    assert saved.json()["document"]["seed"] == 55
    assert len(saved.json()["document"]["objects"]) == 1

    restored = client.get(f"/api/v1/workspace/projects/{project_id}/world")
    assert restored.status_code == 200
    assert restored.json()["world"]["width"] == 112
    assert restored.json()["objects"][0]["name"] == "Signal beacon"
    assert restored.json()["terrain_edits"][0]["operation"] == "raise"

    task_response = client.post(
        f"/api/v1/workspace/projects/{project_id}/tasks",
        json={
            "title": "Polish environment lighting",
            "description": "Review the outpost light balance.",
            "category": "Art",
            "priority": "high",
            "assignee": "Lighting Artist",
            "status": "backlog",
            "due_date": "2026-12-15",
        },
    )
    assert task_response.status_code == 201
    task = task_response.json()["task"]
    assert task["projectId"] == project_id
    assert task["dueDate"] == "2026-12-15"

    moved = client.put(
        f"/api/v1/workspace/projects/{project_id}/tasks/{task['id']}",
        json={
            "title": "Polish environment lighting",
            "description": "Review the outpost light balance.",
            "category": "Art",
            "priority": "high",
            "assignee": "Lighting Artist",
            "status": "in_review",
            "due_date": "2026-12-15",
        },
    )
    assert moved.status_code == 200
    assert moved.json()["task"]["status"] == "in_review"

    listed = client.get(f"/api/v1/workspace/projects/{project_id}/tasks")
    assert listed.status_code == 200
    assert listed.json()["tasks"][0]["id"] == task["id"]
    deleted = client.delete(f"/api/v1/workspace/projects/{project_id}/tasks/{task['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/workspace/projects/{project_id}/tasks").json()["tasks"] == []


def test_world_document_cannot_be_read_or_written_by_another_account(tmp_path):
    owner_client = make_client(tmp_path, "creator-owner")
    created = owner_client.post(
        "/api/v1/workspace/projects",
        json={"name": "Private World", "description": "", "document": {}},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    task_response = owner_client.post(
        f"/api/v1/workspace/projects/{project_id}/tasks",
        json={"title":"Owner-only task"},
    )
    assert task_response.status_code == 201
    task_id = task_response.json()["task"]["id"]

    other_client = make_client(tmp_path, "creator-other")
    world_document = owner_client.get(f"/api/v1/workspace/projects/{project_id}/world").json()
    assert other_client.get(f"/api/v1/workspace/projects/{project_id}/world").status_code == 404
    assert other_client.put(
        f"/api/v1/workspace/projects/{project_id}/world",
        json=world_document,
    ).status_code == 404

    assert other_client.get(f"/api/v1/workspace/projects/{project_id}/tasks").status_code == 404
    assert other_client.post(
        f"/api/v1/workspace/projects/{project_id}/tasks",
        json={"title":"Attempted cross-account task"},
    ).status_code == 404
    assert other_client.put(
        f"/api/v1/workspace/projects/{project_id}/tasks/{task_id}",
        json={"title":"Hijack task"},
    ).status_code == 404
    assert other_client.delete(
        f"/api/v1/workspace/projects/{project_id}/tasks/{task_id}"
    ).status_code == 404



def test_job_history_and_artifact_download_links_survive_registry_restart(tmp_path):
    manager = ProjectManager(tmp_path / "projects")
    first_jobs = JobRegistry()
    app = FastAPI()

    @app.middleware("http")
    async def attach_test_identity(request: Request, call_next):
        request.state.nexora_user_id = "creator-one"
        request.state.nexora_user = {"id": "creator-one"}
        return await call_next(request)

    register_nexora_workspace_routes(app, manager, first_jobs)
    first_client = TestClient(app)
    created = first_client.post(
        "/api/v1/workspace/projects",
        json={"name": "Durable History", "description": "Job journal test", "document": {}},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    job = first_jobs.add(Job.create(project_id, kind="build.export", target="windows"))
    first_jobs.update(
        job.id,
        state=JobState.COMPLETED,
        progress=100,
        message="Windows build exported",
    )
    folder = manager.path_for(project_id)
    job_root = folder / "workspace_jobs"
    job_root.mkdir(exist_ok=True)
    (job_root / f"{job.id}.owner.json").write_text(
        json.dumps({"user_id": "creator-one"}), encoding="utf-8"
    )
    artifact = folder / "artifacts" / "build.log"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("Recovered build log", encoding="utf-8")
    (job_root / f"{job.id}.json").write_text(
        json.dumps({"artifacts": [{
            "id": "windows-log",
            "filename": artifact.name,
            "path": artifact.relative_to(folder).as_posix(),
            "content_type": "text/plain",
        }]}),
        encoding="utf-8",
    )

    # Simulate a fresh Local Agent process with an empty in-memory registry.
    restarted_app = FastAPI()

    @restarted_app.middleware("http")
    async def attach_restarted_identity(request: Request, call_next):
        request.state.nexora_user_id = "creator-one"
        request.state.nexora_user = {"id": "creator-one"}
        return await call_next(request)

    register_nexora_workspace_routes(restarted_app, manager, JobRegistry())
    restarted_client = TestClient(restarted_app)
    listed = restarted_client.get(f"/api/v1/workspace/projects/{project_id}/jobs")
    assert listed.status_code == 200
    restored_job = listed.json()["jobs"][0]
    assert restored_job["id"] == job.id
    assert restored_job["state"] == "completed"
    assert restored_job["message"] == "Windows build exported"
    assert restored_job["artifacts"][0]["download_url"].endswith(
        f"/api/v1/workspace/jobs/{job.id}/artifacts/windows-log/download"
    )

    downloaded = restarted_client.get(restored_job["artifacts"][0]["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.text == "Recovered build log"
