import json
from pathlib import Path

import pytest

from core.movie_pipeline.models import RightsDeclaration, StageState, new_pipeline
from core.movie_pipeline.service import PipelineStore
from core.movie_pipeline import intelligence


RIGHTS = RightsDeclaration(has_video_rights=True, has_photo_rights=True, likeness_consent=True, accepts_original_assets_only=True)


def test_ollama_client_rejects_remote_endpoint():
    with pytest.raises(intelligence.IntelligenceError, match="loopback"):
        intelligence.OllamaLocalClient("https://example.com")


def test_story_intelligence_writes_vision_and_story_outputs(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    store = PipelineStore(project)
    doc = new_pipeline("project", RIGHTS)
    upload = store.folder / "uploads"
    upload.mkdir()
    photo = upload / "portrait.jpg"
    photo.write_bytes(b"portrait")
    movie = upload / "movie.mp4"
    movie.write_bytes(b"movie")
    doc.source_photo = {"storage_key": "movie_pipeline/uploads/portrait.jpg"}
    (upload / "portrait.jpg").write_bytes(b"portrait-photo")
    doc.source_video = {"storage_key": "movie_pipeline/uploads/movie.mp4"}
    store.save(doc)

    analysis_dir = store.folder / "analysis" / "revision-0"
    frame_dir = analysis_dir / "keyframes"
    frame_dir.mkdir(parents=True)
    (frame_dir / "frame-001.jpg").write_bytes(b"frame")
    manifest = {
        "keyframes": [{"index": 1, "timestamp_seconds": 3.0, "path": "keyframes/frame-001.jpg"}],
        "media": {"duration_seconds": 20},
        "transcription": {"status": "skipped"},
    }
    manifest_path = analysis_dir / "analysis.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    current = store.load()
    record = current.stages[0]
    record.state = StageState.REVIEW
    record.output = {"manifest": str(manifest_path.relative_to(project))}
    store.save(current)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def require_model(self, model):
            return None
        def generate_json(self, model, prompt, images=None):
            if images:
                return {"visual_style": "moody science fiction", "events": [], "locations": [], "recurring_characters": []}
            return {
                "title": "The Last Signal", "missions": [{"id": "m" + str(i)} for i in range(4)], "level_progression": [{"level": i} for i in range(3)],
                "supporting_characters": [], "locations": [], "enemies": [], "items": [],
            }

    monkeypatch.setattr(intelligence, "OllamaLocalClient", FakeClient)
    monkeypatch.setenv("PGF_VISION_MODEL", "vision-local")
    monkeypatch.setenv("PGF_STORY_MODEL", "story-local")
    result = intelligence.run_story_intelligence(project)
    assert result["story"]["title"] == "The Last Signal"
    assert (analysis_dir / "vision-analysis.json").is_file()
    assert (analysis_dir / "storyboard.json").is_file()
    final = store.load().stages[0]
    assert final.state == StageState.REVIEW
    assert final.output["mission_count"] == 4


def test_story_intelligence_requires_review_state(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    PipelineStore(project).save(new_pipeline("project", RIGHTS))
    with pytest.raises(ValueError, match="must be in REVIEW"):
        intelligence.run_story_intelligence(project)


def test_story_edit_api_persists_creator_changes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import services.api.main as api

    monkeypatch.setattr(api, "manager", api.ProjectManager(tmp_path))
    client = TestClient(api.app)
    project = client.post("/api/projects", json={"name": "Story Edit"}).json()
    pid = project["id"]
    client.post(f"/api/projects/{pid}/movie-pipeline", json={"rights": RIGHTS.model_dump(mode="json")})
    folder = api.manager.path_for(pid)
    store = PipelineStore(folder)
    document = store.load()
    analysis = document.stages[0]
    analysis.state = StageState.REVIEW
    story_path = store.folder / "analysis" / "revision-0" / "storyboard.json"
    story_path.parent.mkdir(parents=True)
    initial = {
        "status": "ready_for_creator_review",
        "story": {
            "title": "Original", "logline": "Original logline",
            "missions": [{"id": str(i), "title": "Mission " + str(i), "objective": "Objective"} for i in range(4)],
            "level_progression": [{"level": i, "name": "Level " + str(i), "primary_challenge": "Challenge"} for i in range(3)],
            "supporting_characters": [], "locations": [], "enemies": [], "items": [],
        },
    }
    story_path.write_text(json.dumps(initial), encoding="utf-8")
    analysis.output = {"story_manifest": str(story_path.relative_to(folder))}
    store.save(document)
    edited = dict(initial["story"])
    edited["title"] = "Creator Original Game"
    response = client.put(
        f"/api/projects/{pid}/movie-pipeline/stages/analysis/intelligence",
        json={"story": edited},
    )
    assert response.status_code == 200
    assert response.json()["story"]["title"] == "Creator Original Game"
    fetched = client.get(f"/api/projects/{pid}/movie-pipeline/stages/analysis/intelligence")
    assert fetched.status_code == 200
    assert fetched.json()["story"]["title"] == "Creator Original Game"


def test_intelligence_api_queues_and_completes_local_job(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import services.api.main as api

    monkeypatch.setattr(api, "manager", api.ProjectManager(tmp_path))
    monkeypatch.setattr(api, "run_story_intelligence", lambda folder: {"story": {"title": "Local Story", "missions": [{}, {}, {}, {}], "level_progression": [{}, {}, {}]}})
    client = TestClient(api.app)
    project = client.post("/api/projects", json={"name": "Intelligence Job"}).json()
    pid = project["id"]
    client.post(f"/api/projects/{pid}/movie-pipeline", json={"rights": RIGHTS.model_dump(mode="json")})
    store = PipelineStore(api.manager.path_for(pid))
    document = store.load()
    document.stages[0].state = StageState.REVIEW
    store.save(document)
    response = client.post(f"/api/projects/{pid}/movie-pipeline/stages/analysis/intelligence/run")
    assert response.status_code == 202
    job = client.get(f"/api/jobs/{response.json()['id']}")
    assert job.status_code == 200
    assert job.json()["state"] == "COMPLETED"
