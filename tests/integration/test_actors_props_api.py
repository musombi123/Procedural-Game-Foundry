from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
import services.api.main as api
from core.movie_pipeline.models import RightsDeclaration, StageId, StageState
from core.movie_pipeline.service import PipelineStore

RIGHTS=RightsDeclaration(has_video_rights=False,has_photo_rights=True,likeness_consent=True,accepts_original_assets_only=True)

def ready_actors_props(tmp_path, monkeypatch):
    monkeypatch.setattr(api,"manager",api.ProjectManager(tmp_path))
    client=TestClient(api.app)
    project=client.post("/api/projects",json={"name":"Actors Test"}).json(); pid=project["id"]
    client.post(f"/api/projects/{pid}/movie-pipeline",json={"rights":RIGHTS.model_dump(mode="json")})
    folder=api.manager.path_for(pid); store=PipelineStore(folder); doc=store.load()
    records={item.stage:item for item in doc.stages}
    records[StageId.PLAYER].state=StageState.APPROVED
    records[StageId.ENVIRONMENT].state=StageState.APPROVED
    records[StageId.ACTORS_PROPS].state=StageState.READY
    store.save(doc)
    return client,pid,store

def test_actors_props_requires_environment_approval(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"manager",api.ProjectManager(tmp_path))
    client=TestClient(api.app); project=client.post("/api/projects",json={"name":"Gate Test"}).json(); pid=project["id"]
    client.post(f"/api/projects/{pid}/movie-pipeline",json={"rights":RIGHTS.model_dump(mode="json")})
    response=client.post(f"/api/projects/{pid}/movie-pipeline/actors-props/build",json={"actors":[{"id":"npc-1","name":"Guard"}],"props":[]})
    assert response.status_code==409

def test_actors_props_build_and_review(tmp_path,monkeypatch):
    client,pid,store=ready_actors_props(tmp_path,monkeypatch)
    monkeypatch.setattr(api.shutil,"which",lambda name:"/usr/bin/blender")
    def fake_run(command,**kwargs):
        output=Path(command[command.index("--output")+1]); output.write_bytes(b"glb"+b"x"*2048)
        output.with_suffix(".manifest.json").write_text('{"actors":[],"props":[]}',encoding="utf-8")
        return SimpleNamespace(stdout='{"actors":1,"props":1}',stderr="")
    monkeypatch.setattr(api.subprocess,"run",fake_run)
    response=client.post(f"/api/projects/{pid}/movie-pipeline/actors-props/build",json={
        "actors":[{"id":"guard-1","name":"Gate Guard","kind":"npc","behavior":"patrol"}],
        "props":[{"id":"crate-1","name":"Supply Crate","kind":"container","interaction":"open"}]})
    assert response.status_code==200,response.text
    payload=response.json()
    assert payload["stage"]["state"]=="REVIEW"
    assert payload["actor_count"]==1 and payload["prop_count"]==1
    assert payload["glb_scene"].endswith("actors-props.glb")
    assert Path(store.folder.parent / payload["glb_scene"]).is_file()
    approved=client.post(f"/api/projects/{pid}/movie-pipeline/stages/actors_props/approve",json={"note":"Reviewed"})
    assert approved.status_code==200
    assert next(s for s in approved.json()["stages"] if s["stage"]=="audio")["state"]=="READY"

def test_actors_props_reject_duplicate_ids_and_empty_build(tmp_path,monkeypatch):
    client,pid,_=ready_actors_props(tmp_path,monkeypatch)
    empty=client.post(f"/api/projects/{pid}/movie-pipeline/actors-props/build",json={"actors":[],"props":[]})
    assert empty.status_code==400
    duplicate=client.post(f"/api/projects/{pid}/movie-pipeline/actors-props/build",json={
        "actors":[{"id":"same","name":"Guard"}],"props":[{"id":"same","name":"Crate"}]})
    assert duplicate.status_code==400

def test_blender_actor_script_has_valid_python_syntax():
    script=Path(__file__).resolve().parents[2]/"blender"/"scripts"/"build_actors_props.py"
    compile(script.read_text(encoding="utf-8"),str(script),"exec")
