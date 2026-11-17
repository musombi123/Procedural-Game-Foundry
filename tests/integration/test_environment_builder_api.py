from types import SimpleNamespace
from pathlib import Path
from fastapi.testclient import TestClient
import services.api.main as api
from core.movie_pipeline.models import RightsDeclaration, StageId, StageState
from core.movie_pipeline.service import PipelineStore

RIGHTS=RightsDeclaration(has_video_rights=False,has_photo_rights=True,likeness_consent=True,accepts_original_assets_only=True)

def test_environment_requires_player_approval_and_exports_glb(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"manager",api.ProjectManager(tmp_path))
    client=TestClient(api.app)
    project=client.post("/api/projects",json={"name":"World Gate"}).json(); pid=project["id"]
    assert client.post(f"/api/projects/{pid}/movie-pipeline",json={"rights":RIGHTS.model_dump(mode="json")}).status_code==201
    folder=api.manager.path_for(pid); store=PipelineStore(folder); doc=store.load()
    photo=store.folder/"uploads"/"portrait.jpg"; photo.parent.mkdir(parents=True,exist_ok=True); photo.write_bytes(b"portrait")
    doc.source_photo={"storage_key":"movie_pipeline/uploads/portrait.jpg"}; store.save(doc)
    assert client.put(f"/api/projects/{pid}/movie-pipeline/story",json={"mode":"story","title":"World"}).status_code==200
    blocked=client.post(f"/api/projects/{pid}/movie-pipeline/environment/build")
    assert blocked.status_code==409
    doc=store.load(); player=next(s for s in doc.stages if s.stage==StageId.PLAYER)
    player.state=StageState.REVIEW; store.save(doc)
    store.approve(StageId.PLAYER,"Avatar inspected")
    monkeypatch.setattr(api.shutil,"which",lambda name:"/usr/bin/blender")
    def fake_run(command,**kwargs):
        output=command[command.index("--output")+1]; Path(output).write_bytes(b"glb"+b"x"*2048)
        return SimpleNamespace(stdout="",stderr="")
    monkeypatch.setattr(api.subprocess,"run",fake_run)
    response=client.post(f"/api/projects/{pid}/movie-pipeline/environment/build")
    assert response.status_code==200,response.text
    assert response.json()["stage"]["state"]=="REVIEW"
    assert response.json()["glb_scene"].endswith("environment.glb")
