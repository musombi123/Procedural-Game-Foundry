from fastapi.testclient import TestClient
import services.api.main as api
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.service import PipelineStore

RIGHTS = {
    "has_video_rights": True,
    "has_photo_rights": True,
    "likeness_consent": True,
    "accepts_original_assets_only": True,
}

def test_movie_pipeline_requires_all_rights_and_persists_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "manager", api.ProjectManager(tmp_path))
    client = TestClient(api.app)
    project = client.post("/api/projects", json={"name": "Film Inspired Game"}).json()
    pid = project["id"]

    rejected = client.post(f"/api/projects/{pid}/movie-pipeline", json={"rights": {**RIGHTS, "likeness_consent": False}})
    assert rejected.status_code == 400

    created = client.post(f"/api/projects/{pid}/movie-pipeline", json={"rights": RIGHTS})
    assert created.status_code == 201
    stages = created.json()["stages"]
    assert stages[0]["stage"] == "analysis" and stages[0]["state"] == "READY"
    assert all(stage["state"] == "LOCKED" for stage in stages[1:])

    store = PipelineStore(api.manager.path_for(pid))
    document = store.load()
    document.stages[0].state = StageState.RUNNING
    store.save(document)
    store.mark_review(StageId.ANALYSIS, {"brief": "approved content is creator-reviewed"}, "Brief ready for review")

    approved = client.post(f"/api/projects/{pid}/movie-pipeline/stages/analysis/approve", json={"note": "Looks good"})
    assert approved.status_code == 200
    data = approved.json()
    assert data["stages"][0]["state"] == "APPROVED"
    assert data["stages"][1]["state"] == "READY"
    assert data["active_stage"] == "player"

    regenerated = client.post(f"/api/projects/{pid}/movie-pipeline/stages/analysis/regenerate")
    assert regenerated.status_code == 200
    data = regenerated.json()
    assert data["stages"][0]["state"] == "READY"
    assert data["stages"][0]["revision"] == 1
    assert data["stages"][1]["state"] == "LOCKED"
    assert data["stages"][1]["revision"] == 1


def test_cannot_approve_stage_without_review_output(tmp_path):
    store = PipelineStore(tmp_path)
    from core.movie_pipeline.models import RightsDeclaration, new_pipeline
    store.save(new_pipeline("test-project", RightsDeclaration(**RIGHTS)))
    try:
        store.approve(StageId.ANALYSIS)
    except ValueError as exc:
        assert "REVIEW" in str(exc)
    else:
        raise AssertionError("Approval without a reviewed output must be rejected")


def test_media_uploads_are_signature_checked_and_project_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "manager", api.ProjectManager(tmp_path))
    client = TestClient(api.app)
    project = client.post("/api/projects", json={"name": "Upload Test"}).json()
    pid = project["id"]
    created = client.post(f"/api/projects/{pid}/movie-pipeline", json={"rights": RIGHTS})
    assert created.status_code == 201

    bad = client.post(f"/api/projects/{pid}/movie-pipeline/source/photo", files={"file": ("portrait.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 400

    photo_bytes = bytes.fromhex("ffd8ff") + b"test-jpeg-payload"
    photo = client.post(f"/api/projects/{pid}/movie-pipeline/source/photo", files={"file": ("portrait.jpg", photo_bytes, "image/jpeg")})
    assert photo.status_code == 201
    assert photo.json()["metadata"]["size_bytes"] == len(photo_bytes)

    video_bytes = bytes.fromhex("00000018667479706d703432") + b"test-video-payload"
    video = client.post(f"/api/projects/{pid}/movie-pipeline/source/video", files={"file": ("movie.mp4", video_bytes, "video/mp4")})
    assert video.status_code == 201
    assert video.json()["metadata"]["sha256"]
    restored = client.get(f"/api/projects/{pid}/movie-pipeline").json()
    assert restored["source_photo"]["filename"] == "player-portrait.jpg"
    assert restored["source_video"]["filename"] == "source-movie.mp4"

    duplicate = client.post(f"/api/projects/{pid}/movie-pipeline/source/photo", files={"file": ("another.jpg", photo_bytes, "image/jpeg")})
    assert duplicate.status_code == 409
