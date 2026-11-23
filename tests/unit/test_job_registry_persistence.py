from __future__ import annotations

import json

from core.orchestration.jobs import Job, JobRegistry, JobState
from core.project_engine.manager import ProjectManager
from core.project_engine.models import ProjectCreate


def make_project(tmp_path, name="Durable Jobs"):
    manager = ProjectManager(tmp_path / "projects")
    project = manager.create(ProjectCreate(name=name))
    return manager, project.id


def test_running_job_is_recovered_as_interrupted_after_agent_restart(tmp_path):
    manager, project_id = make_project(tmp_path)
    registry = JobRegistry(manager)
    job = registry.add(Job.create(project_id, kind="build.export", target="windows"))
    registry.update(
        job.id,
        state=JobState.RUNNING,
        progress=64,
        message="Exporting Windows desktop build",
    )

    job_root = manager.path_for(project_id) / "workspace_jobs"
    artifact = job_root / f"{job.id}.json"
    artifact.write_text(json.dumps({"artifacts": [{
        "id": "windows",
        "filename": "Game.exe",
        "path": "artifacts/windows/Game.exe",
        "content_type": "application/octet-stream",
    }]}), encoding="utf-8")

    restarted = JobRegistry(manager)
    recovered = restarted.list_for_project(project_id)

    assert len(recovered) == 1
    assert recovered[0].id == job.id
    assert recovered[0].kind == "build.export"
    assert recovered[0].target == "windows"
    assert recovered[0].state is JobState.INTERRUPTED
    assert recovered[0].progress == 64
    assert "restarted" in recovered[0].message.lower()

    # A second restart must retain the terminal recovery state and artifact reference.
    second_restart = JobRegistry(manager).list_for_project(project_id)
    assert second_restart[0].state is JobState.INTERRUPTED
    assert json.loads(artifact.read_text(encoding="utf-8"))["artifacts"][0]["filename"] == "Game.exe"


def test_completed_job_and_artifact_history_survive_registry_restart(tmp_path):
    manager, project_id = make_project(tmp_path, "Completed Job")
    registry = JobRegistry(manager)
    job = registry.add(Job.create(project_id, kind="scene.generate", target="desktop"))
    registry.update(
        job.id,
        state=JobState.COMPLETED,
        progress=100,
        message="Scene generated and validated",
    )
    artifact_manifest = manager.path_for(project_id) / "workspace_jobs" / f"{job.id}.json"
    artifact_manifest.write_text(json.dumps({"artifacts": [{
        "id": "scene-log",
        "filename": "scene.log",
        "path": "artifacts/scene.log",
        "content_type": "text/plain",
    }]}), encoding="utf-8")

    restored = JobRegistry(manager).list_for_project(project_id)
    assert restored[0].state is JobState.COMPLETED
    assert restored[0].message == "Scene generated and validated"
    assert restored[0].kind == "scene.generate"
    assert restored[0].as_dict()["target"] == "desktop"


def test_legacy_job_metadata_is_visible_as_recovered_not_falsely_completed(tmp_path):
    manager, project_id = make_project(tmp_path, "Legacy Job")
    job_id = "legacy-job-123"
    job_root = manager.path_for(project_id) / "workspace_jobs"
    job_root.mkdir(exist_ok=True)
    (job_root / f"{job_id}.owner.json").write_text(
        json.dumps({"user_id": "creator-one"}), encoding="utf-8"
    )
    (job_root / f"{job_id}.json").write_text(
        json.dumps({"artifacts": []}), encoding="utf-8"
    )

    recovered = JobRegistry(manager).list_for_project(project_id)
    assert len(recovered) == 1
    assert recovered[0].id == job_id
    assert recovered[0].state is JobState.RECOVERED
    assert "not saved" in recovered[0].message.lower()


def test_job_history_is_scoped_to_the_project(tmp_path):
    manager, first_id = make_project(tmp_path, "First Project")
    _, second_id = make_project(tmp_path, "Second Project")
    registry = JobRegistry(manager)
    first_job = registry.add(Job.create(first_id, kind="playtest"))
    registry.add(Job.create(second_id, kind="build.export", target="linux"))

    assert [job.id for job in JobRegistry(manager).list_for_project(first_id)] == [first_job.id]
    assert JobRegistry(manager).list_for_project(second_id)[0].project_id == second_id
