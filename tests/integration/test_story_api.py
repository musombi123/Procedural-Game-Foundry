import json
from fastapi.testclient import TestClient
import services.api.main as api
from core.movie_pipeline.models import RightsDeclaration
from core.movie_pipeline.service import PipelineStore

RIGHTS=RightsDeclaration(has_video_rights=True,has_photo_rights=True,likeness_consent=True,accepts_original_assets_only=True)

def test_story_first_mode_saves_without_movie_video(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"manager",api.ProjectManager(tmp_path))
    client=TestClient(api.app)
    project=client.post("/api/projects",json={"name":"Story First"}).json()
    pid=project["id"]
    created=client.post(f"/api/projects/{pid}/movie-pipeline",json={"rights":RIGHTS.model_dump(mode="json")})
    assert created.status_code==201
    store=PipelineStore(api.manager.path_for(pid))
    document=store.load()
    document.source_photo={"filename":"portrait.png","storage_key":"movie_pipeline/uploads/portrait.png"}
    store.save(document)
    response=client.put(f"/api/projects/{pid}/movie-pipeline/story",json={
        "mode":"story","title":"The Crossing","premise":"A pilot crosses a flooded continent.",
        "player_role":"Pilot","instructions":"Rescue survivors and avoid combat.","mission_count":4
    })
    assert response.status_code==200
    saved=client.get(f"/api/projects/{pid}/movie-pipeline/story")
    assert saved.status_code==200
    assert saved.json()["player"]["identity_source"]=="uploaded_portrait"
    assert saved.json()["instructions"]=="Rescue survivors and avoid combat."
