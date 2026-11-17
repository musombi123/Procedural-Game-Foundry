from types import SimpleNamespace
from fastapi.testclient import TestClient
import services.api.main as api
from core.movie_pipeline.models import RightsDeclaration
from core.movie_pipeline.service import PipelineStore

RIGHTS=RightsDeclaration(has_video_rights=True,has_photo_rights=True,likeness_consent=True,accepts_original_assets_only=True)

def test_story_first_unlocks_player_and_builds_procedural_glb(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"manager",api.ProjectManager(tmp_path))
    client=TestClient(api.app)
    project=client.post("/api/projects",json={"name":"Portrait Avatar"}).json()
    pid=project["id"]
    created=client.post(f"/api/projects/{pid}/movie-pipeline",json={"rights":RIGHTS.model_dump(mode="json")})
    assert created.status_code==201
    folder=api.manager.path_for(pid)
    store=PipelineStore(folder)
    document=store.load()
    portrait=store.folder/"uploads"/"player-portrait.jpg"
    portrait.parent.mkdir(parents=True,exist_ok=True)
    portrait.write_bytes(bytes.fromhex("ffd8ff")+"portrait")
    document.source_photo={"filename":portrait.name,"storage_key":"movie_pipeline/uploads/player-portrait.jpg","sha256":"abc123"}
    store.save(document)
    saved=client.put(f"/api/projects/{pid}/movie-pipeline/story",json={"mode":"story","title":"My Story","premise":"A journey","mission_count":3})
    assert saved.status_code==200
    ready=store.load()
    assert next(s for s in ready.stages if s.stage.value=="analysis").state.value=="APPROVED"
    assert next(s for s in ready.stages if s.stage.value=="player").state.value=="READY"
    monkeypatch.setattr(api.shutil,"which",lambda name:"/usr/bin/blender")
    def fake_run(command,**kwargs):
        output=command[command.index("--output")+1]
        from pathlib import Path
        Path(output).write_bytes(b"glb"+b"x"*2048)
        return SimpleNamespace(stdout='{"bone_count":16}\n',stderr="")
    monkeypatch.setattr(api.subprocess,"run",fake_run)
    response=client.post(f"/api/projects/{pid}/movie-pipeline/player/build",json={"proportions":{"height":1.82,"build":1.1}})
    assert response.status_code==200, response.text
    assert response.json()["generated"] is True
    assert response.json()["glb_scene"].endswith("player-avatar.glb")
    assert response.json()["stage"]["state"]=="REVIEW"
    assert response.json()["stage"]["output"]["bone_count"]==16
    asset_path=response.json()["glb_scene"]
    download=client.get(f"/api/projects/{pid}/movie-pipeline/assets/{asset_path}")
    assert download.status_code==200
    assert download.content.startswith(b"glb")
