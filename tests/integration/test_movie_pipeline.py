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
